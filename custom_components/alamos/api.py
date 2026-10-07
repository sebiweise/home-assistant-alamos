"""Client for the Alamos availability API.

The API currently offers a single endpoint which lets a person answer
("Zusage"/"Absage") every alarm received within the last three minutes:

    {base}/fe2/feedback/user/external?authToken=<key>&mode=accept|reject
        [&suppressNotification=true]

Return codes:
    200  feedback stored for at least one alarm
    204  no alarm within the last three minutes
    400  authToken or mode missing
    403  wrong API key
    409  smart home subscription / licence missing
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from http import HTTPStatus
import logging

import aiohttp

from .const import FEEDBACK_MODES, FEEDBACK_PATH

_LOGGER = logging.getLogger(__name__)

REQUEST_TIMEOUT = 15


class AlamosApiError(Exception):
    """Generic Alamos API error."""


class AlamosAuthError(AlamosApiError):
    """The API key was rejected (HTTP 403)."""


class AlamosSubscriptionError(AlamosApiError):
    """The smart home subscription or licence is missing (HTTP 409)."""


@dataclass(frozen=True, slots=True)
class FeedbackResult:
    """Result of a feedback request."""

    mode: str
    status: int

    @property
    def success(self) -> bool:
        """Return True if the feedback was stored for at least one alarm."""
        return self.status == HTTPStatus.OK

    @property
    def result(self) -> str:
        """Return a machine-readable result."""
        return "success" if self.success else "no_alarm"


class AlamosApiClient:
    """Minimal async client for the Alamos availability API."""

    def __init__(
        self, session: aiohttp.ClientSession, api_key: str, base_url: str
    ) -> None:
        """Initialize the client."""
        self._session = session
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")

    async def async_send_feedback(
        self, mode: str, suppress_notification: bool = False
    ) -> FeedbackResult:
        """Answer all alarms of the last three minutes."""
        if mode not in FEEDBACK_MODES:
            raise ValueError(f"Invalid feedback mode: {mode}")

        params = {"authToken": self._api_key, "mode": mode}
        if suppress_notification:
            params["suppressNotification"] = "true"
        url = f"{self._base_url}{FEEDBACK_PATH}"

        try:
            async with asyncio.timeout(REQUEST_TIMEOUT):
                status = await self._request("GET", url, params)
                if status == HTTPStatus.METHOD_NOT_ALLOWED:
                    status = await self._request("POST", url, params)
        except (TimeoutError, aiohttp.ClientError) as err:
            raise AlamosApiError(f"Error communicating with Alamos: {err}") from err

        _LOGGER.debug("Feedback '%s' answered with HTTP %s", mode, status)

        if status in (HTTPStatus.OK, HTTPStatus.NO_CONTENT):
            return FeedbackResult(mode=mode, status=status)
        if status in (HTTPStatus.FORBIDDEN, HTTPStatus.UNAUTHORIZED):
            raise AlamosAuthError("The Alamos API key is invalid")
        if status == HTTPStatus.CONFLICT:
            raise AlamosSubscriptionError(
                "Smart home subscription or licence is missing"
            )
        if status == HTTPStatus.BAD_REQUEST:
            raise AlamosApiError("Alamos rejected the request (missing parameters)")
        raise AlamosApiError(f"Unexpected response from Alamos: HTTP {status}")

    async def _request(self, method: str, url: str, params: dict[str, str]) -> int:
        async with self._session.request(method, url, params=params) as resp:
            await resp.read()
            return resp.status
