"""Webhook receiver for aPager PRO and AMweb webhooks.

* aPager PRO ("Allgemeine Webhooks") calls the URL via GET with the keyword and
  unit as query parameters or via POST with a UTF-8 JSON body.
* AMweb calls the URL via GET for every new alarm and, depending on the
  setting, once no alarm is open anymore. For the latter, the URL is configured
  with ``?event=clear`` appended.
* For a recall (Rückalarm / cancelled alarm), e.g. a second aPager PRO webhook,
  the URL is configured with ``?event=recall`` appended.
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
    ATTR_DATA,
    ATTR_KEYWORD,
    ATTR_RECALL,
    ATTR_UNIT,
    CONF_KEYWORD_PARAM,
    CONF_TEST_KEYWORDS,
    CONF_UNIT_FILTER,
    CONF_UNIT_PARAM,
    DEFAULT_KEYWORD_PARAM,
    DEFAULT_UNIT_PARAM,
    EVENT_TYPE_ALARM,
    EVENT_TYPE_CLEARED,
    WEBHOOK_CLEAR_VALUES,
    WEBHOOK_EVENT_PARAM,
    WEBHOOK_RECALL_VALUES,
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


def _matches_unit_filter(unit: str | None, unit_filter: list[str]) -> bool:
    """Return True if the alarm belongs to one of the configured units.

    Alarms without a unit are always accepted so that no real alarm gets lost
    when the unit is not transmitted.
    """
    if not unit_filter or unit is None:
        return True
    return unit.casefold() in {item.casefold() for item in unit_filter}


def _is_test_alarm(keyword: str | None, test_keywords: list[str]) -> bool:
    """Return True if the keyword contains one of the test alarm keywords."""
    if not keyword or not test_keywords:
        return False
    folded = keyword.casefold()
    return any(item.casefold() in folded for item in test_keywords)


async def _async_read_request(request: web.Request) -> dict[str, Any] | web.Response:
    """Read the payload or return an error response."""
    try:
        payload = await _async_read_payload(request)
    except ValueError as err:
        _LOGGER.warning("Could not parse Alamos webhook payload: %s", err)
        return web.Response(status=400, text="invalid payload")
    _LOGGER.debug("Alamos webhook received (%s): %s", request.method, payload)
    return payload


def _keyword_and_unit(
    entry: ConfigEntry, payload: dict[str, Any]
) -> tuple[str | None, str | None]:
    keyword_param = entry.options.get(CONF_KEYWORD_PARAM, DEFAULT_KEYWORD_PARAM)
    unit_param = entry.options.get(CONF_UNIT_PARAM, DEFAULT_UNIT_PARAM)
    return _as_text(payload.get(keyword_param)), _as_text(payload.get(unit_param))


def async_create_webhook_handler(entry: ConfigEntry):
    """Create a webhook handler bound to a config entry."""

    async def async_handle_webhook(
        hass: HomeAssistant, webhook_id: str, request: web.Request
    ) -> web.Response:
        """Handle an incoming webhook call."""
        manager = entry.runtime_data.manager

        payload = await _async_read_request(request)
        if isinstance(payload, web.Response):
            return payload

        event = str(payload.pop(WEBHOOK_EVENT_PARAM, "") or "").strip().lower()
        if event in WEBHOOK_CLEAR_VALUES:
            manager.async_clear(EVENT_TYPE_CLEARED)
            return web.Response(status=200, text="cleared")

        keyword, unit = _keyword_and_unit(entry, payload)

        if not _matches_unit_filter(unit, entry.options.get(CONF_UNIT_FILTER, [])):
            _LOGGER.debug(
                "Ignoring %s for unit %s (unit filter)", event or "alarm", unit
            )
            return web.Response(status=200, text="ignored")

        if event in WEBHOOK_RECALL_VALUES:
            reported = manager.async_recall(
                {
                    ATTR_KEYWORD: keyword,
                    ATTR_UNIT: unit,
                    ATTR_DATA: payload,
                    ATTR_RECALL: True,
                }
            )
            return web.Response(status=200, text="cleared" if reported else "merged")

        if _is_test_alarm(keyword, entry.options.get(CONF_TEST_KEYWORDS, [])):
            reported = manager.async_test_alarm(
                keyword=keyword, unit=unit, data=payload
            )
            return web.Response(status=200, text="test" if reported else "merged")

        new_alarm = manager.async_alarm(
            keyword=keyword,
            unit=unit,
            data=payload,
            source=request.method,
            event_type=EVENT_TYPE_ALARM,
        )
        return web.Response(status=200, text="ok" if new_alarm else "merged")

    return async_handle_webhook
