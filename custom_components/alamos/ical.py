"""iCal feed of Home Assistant calendars for the aPager PRO availability.

aPager PRO can read an iCal URL and set the availability from its entries
("Verfügbarkeit → Planung → Automatische Synchronisation mittels
iCal-Adresse"). The app fetches the URL every 8 hours and imports entries up
to 6 months ahead. This module serves the events of the selected Home
Assistant calendars under a secret webhook URL in that format.

If a calendar cannot be read, the feed answers with an error instead of an
empty calendar, so the app keeps the entries of its last successful sync.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterable
from datetime import date, datetime
from hashlib import sha1
from http import HTTPStatus
import logging
from typing import Any

from aiohttp import web

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import dt as dt_util

from .const import (
    AVAILABILITY_FEED_PERIOD,
    CONF_AVAILABILITY_CALENDARS,
    CONF_AVAILABILITY_KEYWORDS,
)

_LOGGER = logging.getLogger(__name__)

CONTENT_TYPE = "text/calendar"
PRODID = "-//home-assistant-alamos//Availability//EN"
# RFC 5545 3.1: content lines should not be longer than 75 octets.
MAX_LINE_OCTETS = 75
# A hanging calendar must not keep the request of the app open.
CALENDAR_TIMEOUT = 30


class CalendarUnavailableError(HomeAssistantError):
    """A selected calendar could not be read."""


def _escape(value: str) -> str:
    """Escape a TEXT value (RFC 5545 3.3.11)."""
    return (
        value.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
        .replace("\r", "\\n")
    )


def _fold(line: str) -> str:
    """Fold a content line after 75 octets without splitting characters."""
    parts: list[str] = []
    current = ""
    limit = MAX_LINE_OCTETS
    for char in line:
        if len((current + char).encode()) > limit:
            parts.append(current)
            current = ""
            # Continuation lines start with a space, which counts as well.
            limit = MAX_LINE_OCTETS - 1
        current += char
    parts.append(current)
    return "\r\n ".join(parts)


def _format_time(name: str, value: str | date) -> str:
    """Return a DTSTART/DTEND property for a date or a date and time."""
    if isinstance(value, str):
        parsed: date | None = dt_util.parse_datetime(value) if "T" in value else None
        if parsed is None:
            parsed = dt_util.parse_date(value)
        if parsed is None:
            raise ValueError(f"Invalid date: {value}")
        value = parsed
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=dt_util.get_default_time_zone())
        return f"{name}:{dt_util.as_utc(value).strftime('%Y%m%dT%H%M%SZ')}"
    return f"{name};VALUE=DATE:{value.strftime('%Y%m%d')}"


def _matches(event: dict[str, Any], keywords: list[str]) -> bool:
    """Return whether the event title or description contains a keyword."""
    if not keywords:
        return True
    text = f"{event.get('summary') or ''}\n{event.get('description') or ''}".lower()
    return any(keyword.lower() in text for keyword in keywords)


def build_ical(
    events: Iterable[tuple[str, dict[str, Any]]], stamp: datetime, name: str
) -> str:
    """Build an iCalendar document from (entity_id, event) pairs."""
    dtstamp = dt_util.as_utc(stamp).strftime("%Y%m%dT%H%M%SZ")
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        f"PRODID:{PRODID}",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{_escape(name)}",
    ]
    for entity_id, event in events:
        start = event["start"]
        end = event["end"]
        summary = event.get("summary") or ""
        uid = sha1(
            f"{entity_id}|{start}|{end}|{summary}".encode(), usedforsecurity=False
        ).hexdigest()
        lines += [
            "BEGIN:VEVENT",
            f"UID:{uid}@alamos.home-assistant",
            f"DTSTAMP:{dtstamp}",
            _format_time("DTSTART", start),
            _format_time("DTEND", end),
            f"SUMMARY:{_escape(summary)}",
        ]
        if description := event.get("description"):
            lines.append(f"DESCRIPTION:{_escape(description)}")
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    return "".join(f"{_fold(line)}\r\n" for line in lines)


async def async_get_calendar_events(
    hass: HomeAssistant, entity_ids: list[str], keywords: list[str]
) -> list[tuple[str, dict[str, Any]]]:
    """Read the events of the calendars from today until the end of the period."""
    start = dt_util.start_of_local_day()
    end = start + AVAILABILITY_FEED_PERIOD
    events: list[tuple[str, dict[str, Any]]] = []
    for entity_id in entity_ids:
        if hass.states.get(entity_id) is None:
            # Removed from Home Assistant; skip it instead of blocking the feed.
            _LOGGER.warning(
                "Calendar %s for the availability feed not found", entity_id
            )
            continue
        try:
            async with asyncio.timeout(CALENDAR_TIMEOUT):
                response = await hass.services.async_call(
                    "calendar",
                    "get_events",
                    {
                        "entity_id": entity_id,
                        "start_date_time": start,
                        "end_date_time": end,
                    },
                    blocking=True,
                    return_response=True,
                )
        except TimeoutError as err:
            raise CalendarUnavailableError(f"{entity_id}: timeout") from err
        except HomeAssistantError as err:
            raise CalendarUnavailableError(f"{entity_id}: {err}") from err
        result = (response or {}).get(entity_id)
        if not isinstance(result, dict):
            raise CalendarUnavailableError(f"{entity_id}: no events returned")
        events += [
            (entity_id, event)
            for event in result.get("events", [])
            if _matches(event, keywords)
        ]
    return events


def async_create_calendar_handler(
    entry: ConfigEntry,
) -> Callable[[HomeAssistant, str, web.Request], Awaitable[web.Response]]:
    """Return the webhook handler serving the availability feed of an entry."""

    async def _async_handle(
        hass: HomeAssistant, webhook_id: str, request: web.Request
    ) -> web.Response:
        """Serve the feed, or HTTP 503 if a calendar cannot be read."""
        try:
            events = await async_get_calendar_events(
                hass,
                list(entry.options.get(CONF_AVAILABILITY_CALENDARS) or []),
                list(entry.options.get(CONF_AVAILABILITY_KEYWORDS) or []),
            )
            body = build_ical(events, dt_util.utcnow(), entry.title)
        except (HomeAssistantError, ValueError) as err:
            _LOGGER.warning(
                "Availability feed for %s not available: %s", entry.title, err
            )
            return web.Response(status=HTTPStatus.SERVICE_UNAVAILABLE)
        _LOGGER.debug(
            "Availability feed for %s requested, %s events", entry.title, len(events)
        )
        return web.Response(text=body, content_type=CONTENT_TYPE, charset="utf-8")

    return _async_handle
