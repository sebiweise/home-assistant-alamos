"""Webhook receiver for aPager PRO and AMweb webhooks.

* aPager PRO ("Allgemeine Webhooks") calls the URL via GET with the keyword and
  unit as query parameters or via POST with a UTF-8 JSON body.
* AMweb calls the URL via GET for every new alarm and, depending on the
  setting, once no alarm is open anymore. For the latter, the URL is configured
  with ``?event=clear`` appended.
"""

from __future__ import annotations

import json
import logging
from typing import Any
from urllib.parse import parse_qsl

from aiohttp import web

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    CONF_KEYWORD_PARAM,
    CONF_UNIT_PARAM,
    DEFAULT_KEYWORD_PARAM,
    DEFAULT_UNIT_PARAM,
    EVENT_TYPE_ALARM,
    EVENT_TYPE_CLEARED,
    WEBHOOK_CLEAR_VALUES,
    WEBHOOK_EVENT_PARAM,
)

_LOGGER = logging.getLogger(__name__)


async def _async_read_payload(request: web.Request) -> dict[str, Any]:
    """Merge query parameters and the request body into one dict."""
    data: dict[str, Any] = dict(request.query)

    if request.method != "POST" or not request.can_read_body:
        return data

    raw = await request.text()
    if not raw.strip():
        return data

    if request.content_type == "application/x-www-form-urlencoded":
        data.update(parse_qsl(raw, keep_blank_values=True))
        return data

    try:
        body = json.loads(raw)
    except ValueError:
        data["body"] = raw
        return data

    if isinstance(body, dict):
        data.update(body)
    else:
        data["body"] = body
    return data


def _as_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def async_create_webhook_handler(entry: ConfigEntry):
    """Create a webhook handler bound to a config entry."""

    async def async_handle_webhook(
        hass: HomeAssistant, webhook_id: str, request: web.Request
    ) -> web.Response:
        """Handle an incoming webhook call."""
        manager = entry.runtime_data.manager

        try:
            payload = await _async_read_payload(request)
        except ValueError as err:
            _LOGGER.warning("Could not parse Alamos webhook payload: %s", err)
            return web.Response(status=400, text="invalid payload")

        _LOGGER.debug("Alamos webhook received (%s): %s", request.method, payload)

        event = str(payload.pop(WEBHOOK_EVENT_PARAM, "") or "").strip().lower()
        if event in WEBHOOK_CLEAR_VALUES:
            manager.async_clear(EVENT_TYPE_CLEARED)
            return web.Response(status=200, text="cleared")

        keyword_param = entry.options.get(CONF_KEYWORD_PARAM, DEFAULT_KEYWORD_PARAM)
        unit_param = entry.options.get(CONF_UNIT_PARAM, DEFAULT_UNIT_PARAM)

        manager.async_alarm(
            keyword=_as_text(payload.get(keyword_param)),
            unit=_as_text(payload.get(unit_param)),
            data=payload,
            source=request.method,
            event_type=EVENT_TYPE_ALARM,
        )
        return web.Response(status=200, text="ok")

    return async_handle_webhook
