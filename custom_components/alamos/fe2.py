"""Client for the external interface ("Externe Schnittstelle") of Alamos FE2.

The FE2 input plugin "Externe Schnittstelle" accepts UTF-8 JSON in data format
v2 via HTTP POST (it has to be enabled in the input plugin):

    POST {IP}:{PORT}/rest/external/http/alarm/v2    alarms and CLOSE
    POST {IP}:{PORT}/rest/external/http/status/v2   vehicle status

The port is the port of the FE2 web interface (default 83). Every request
carries ``type``, ``timestamp`` (ISO), ``sender``, ``authorization`` (shared
secret, must be listed under "Gültige Absender" of the input) and ``data``.

FE2 answers with a standard HTTP code (200 ok, 400 bad request, 406 input
disabled, 409 conflict with the FE2 settings) and a JSON object
``{"status": "OK|NOT_OK", "error": "..."}``.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from http import HTTPStatus
import json
import logging
from typing import Any

import aiohttp

_LOGGER = logging.getLogger(__name__)

REQUEST_TIMEOUT = 15

ALARM_PATH = "/rest/external/http/alarm/v2"
STATUS_PATH = "/rest/external/http/status/v2"

TYPE_ALARM = "ALARM"
TYPE_CLOSE = "CLOSE"
TYPE_STATUS = "STATUS"


class Fe2Error(Exception):
    """FE2 rejected the request or could not be reached."""

    def __init__(self, message: str, status: int | None = None) -> None:
        """Initialize the error."""
        super().__init__(message)
        self.status = status


@dataclass(frozen=True, slots=True)
class Fe2Result:
    """Answer of FE2."""

    status: int
    body: dict[str, Any] | str | None


class Fe2Client:
    """Minimal async client for the FE2 external interface."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        base_url: str,
        sender: str,
        authorization: str,
    ) -> None:
        """Initialize the client."""
        self._session = session
        self._base_url = base_url.strip().rstrip("/")
        self._sender = sender
        self._authorization = authorization

    def build_payload(
        self, message_type: str, data: dict[str, Any], timestamp: datetime
    ) -> dict[str, Any]:
        """Return the JSON body for a request in data format v2."""
        return {
            "type": message_type,
            "timestamp": timestamp.isoformat(timespec="seconds"),
            "sender": self._sender,
            "authorization": self._authorization,
            "data": data,
        }

    async def async_send_alarm(
        self, data: dict[str, Any], timestamp: datetime
    ) -> Fe2Result:
        """Create or update an alarm."""
        return await self._async_post(
            ALARM_PATH, self.build_payload(TYPE_ALARM, data, timestamp)
        )

    async def async_close_alarm(
        self, external_id: str, timestamp: datetime
    ) -> Fe2Result:
        """Close the alarm with the given external ID."""
        return await self._async_post(
            ALARM_PATH,
            self.build_payload(TYPE_CLOSE, {"externalId": external_id}, timestamp),
        )

    async def async_send_status(
        self, data: dict[str, Any], timestamp: datetime
    ) -> Fe2Result:
        """Send a vehicle status."""
        return await self._async_post(
            STATUS_PATH, self.build_payload(TYPE_STATUS, data, timestamp)
        )

    async def _async_post(self, path: str, payload: dict[str, Any]) -> Fe2Result:
        url = f"{self._base_url}{path}"
        try:
            async with (
                asyncio.timeout(REQUEST_TIMEOUT),
                self._session.post(url, json=payload) as resp,
            ):
                status = resp.status
                text = await resp.text()
        except (TimeoutError, aiohttp.ClientError) as err:
            raise Fe2Error(f"Error communicating with FE2: {err}") from err

        _LOGGER.debug("FE2 %s answered with HTTP %s: %s", path, status, text)
        body = _parse_body(text)
        error = body.get("error") if isinstance(body, dict) else None

        if status != HTTPStatus.OK:
            reason = {
                HTTPStatus.BAD_REQUEST: "bad request",
                HTTPStatus.NOT_ACCEPTABLE: "input disabled",
                HTTPStatus.CONFLICT: "conflict with the FE2 settings",
            }.get(status, "unexpected response")
            raise Fe2Error(
                f"HTTP {status} ({reason}){f': {error}' if error else ''}", status
            )
        if isinstance(body, dict) and body.get("status") == "NOT_OK":
            raise Fe2Error(error or "FE2 answered NOT_OK", status)
        return Fe2Result(status=status, body=body)


def _parse_body(text: str) -> dict[str, Any] | str | None:
    if not text.strip():
        return None
    try:
        body = json.loads(text)
    except ValueError:
        return text
    return body if isinstance(body, dict) else text
