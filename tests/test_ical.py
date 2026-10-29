"""Tests for the iCal availability feed."""

import asyncio
from datetime import datetime
from http import HTTPStatus
from typing import Any
from unittest.mock import patch

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.alamos.const import (
    CONF_ADDITIONAL_WEBHOOK_IDS,
    CONF_AVAILABILITY_CALENDARS,
    CONF_AVAILABILITY_KEYWORDS,
    CONF_CALENDAR_WEBHOOK_ID,
    CONF_WEBHOOK_ID,
    DOMAIN,
)
from custom_components.alamos.ical import _fold, build_ical
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
)
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import HomeAssistantError
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util

WEBHOOK_ID = "test_webhook"
CALENDAR_WEBHOOK_ID = "test_calendar"
CALENDAR = "calendar.dienst"

EVENTS: list[dict[str, Any]] = [
    {
        "start": "2026-11-02T08:00:00+01:00",
        "end": "2026-11-02T16:30:00+01:00",
        "summary": "Frühschicht",
    },
    {
        "start": "2026-11-10",
        "end": "2026-11-13",
        "summary": "Urlaub, Ostsee; Familie",
        "description": "Zeile 1\nZeile 2",
    },
    {
        "start": "2026-11-20T08:00:00+01:00",
        "end": "2026-11-20T16:00:00+01:00",
        "summary": "Abgesagte Schicht",
        "status": "CANCELLED",
    },
]


def _mock_calendar(hass: HomeAssistant, events: list[dict[str, Any]] | None) -> list:
    """Register a calendar entity and a get_events service."""
    calls: list[ServiceCall] = []
    hass.states.async_set(CALENDAR, "off")

    async def _get_events(call: ServiceCall) -> ServiceResponse:
        calls.append(call)
        if events is None:
            raise HomeAssistantError("calendar offline")
        return {CALENDAR: {"events": events}}

    hass.services.async_register(
        "calendar", "get_events", _get_events, supports_response=SupportsResponse.ONLY
    )
    return calls


async def _setup(
    hass: HomeAssistant, options: dict[str, Any] | None = None
) -> MockConfigEntry:
    await async_setup_component(hass, "http", {})
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Feuerwehr",
        data={
            CONF_WEBHOOK_ID: WEBHOOK_ID,
            CONF_ADDITIONAL_WEBHOOK_IDS: [f"test_webhook_{n}" for n in range(2, 6)],
            CONF_CALENDAR_WEBHOOK_ID: CALENDAR_WEBHOOK_ID,
        },
        options=options or {},
        minor_version=3,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_feed(hass: HomeAssistant, hass_client_no_auth) -> None:
    """Test the feed serves the events of the selected calendars."""
    calls = _mock_calendar(hass, EVENTS)
    await _setup(hass, {CONF_AVAILABILITY_CALENDARS: [CALENDAR]})
    client = await hass_client_no_auth()

    resp = await client.get(f"/api/webhook/{CALENDAR_WEBHOOK_ID}")
    assert resp.status == HTTPStatus.OK
    assert resp.content_type == "text/calendar"
    body = await resp.text()

    assert body.startswith("BEGIN:VCALENDAR\r\n")
    assert body.endswith("END:VCALENDAR\r\n")
    assert body.count("BEGIN:VEVENT") == 2
    assert "Abgesagte Schicht" not in body
    assert "DTSTART:20261102T070000Z\r\n" in body
    assert "DTEND:20261102T153000Z\r\n" in body
    assert "SUMMARY:Frühschicht\r\n" in body
    assert "DTSTART;VALUE=DATE:20261110\r\n" in body
    assert "DTEND;VALUE=DATE:20261113\r\n" in body
    assert "SUMMARY:Urlaub\\, Ostsee\\; Familie\r\n" in body
    assert "DESCRIPTION:Zeile 1\\nZeile 2\r\n" in body
    assert "X-WR-CALNAME:Feuerwehr\r\n" in body

    assert len(calls) == 1
    assert calls[0].data["entity_id"] == CALENDAR
    start = calls[0].data["start_date_time"]
    assert (calls[0].data["end_date_time"] - start).days == 183


async def test_feed_keywords(hass: HomeAssistant, hass_client_no_auth) -> None:
    """Test only events with a keyword in title or description are served."""
    _mock_calendar(hass, EVENTS)
    await _setup(
        hass,
        {
            CONF_AVAILABILITY_CALENDARS: [CALENDAR],
            CONF_AVAILABILITY_KEYWORDS: ["URLAUB"],
        },
    )
    client = await hass_client_no_auth()

    body = await (await client.get(f"/api/webhook/{CALENDAR_WEBHOOK_ID}")).text()
    assert body.count("BEGIN:VEVENT") == 1
    assert "Frühschicht" not in body


async def test_feed_calendar_error(hass: HomeAssistant, hass_client_no_auth) -> None:
    """Test a failing calendar returns an error instead of an empty feed."""
    _mock_calendar(hass, None)
    await _setup(hass, {CONF_AVAILABILITY_CALENDARS: [CALENDAR]})
    client = await hass_client_no_auth()

    resp = await client.get(f"/api/webhook/{CALENDAR_WEBHOOK_ID}")
    assert resp.status == HTTPStatus.SERVICE_UNAVAILABLE


async def test_feed_calendar_timeout(hass: HomeAssistant, hass_client_no_auth) -> None:
    """Test a hanging calendar returns an error instead of blocking the app."""
    hass.states.async_set(CALENDAR, "off")
    blocked = asyncio.Event()

    async def _get_events(call: ServiceCall) -> ServiceResponse:
        await blocked.wait()
        return {}

    hass.services.async_register(
        "calendar", "get_events", _get_events, supports_response=SupportsResponse.ONLY
    )
    await _setup(hass, {CONF_AVAILABILITY_CALENDARS: [CALENDAR]})
    client = await hass_client_no_auth()

    with patch("custom_components.alamos.ical.CALENDAR_TIMEOUT", 0):
        resp = await client.get(f"/api/webhook/{CALENDAR_WEBHOOK_ID}")
    assert resp.status == HTTPStatus.SERVICE_UNAVAILABLE
    blocked.set()


async def test_feed_removed_calendar(hass: HomeAssistant, hass_client_no_auth) -> None:
    """Test a calendar removed from Home Assistant is skipped."""
    _mock_calendar(hass, EVENTS)
    await _setup(hass, {CONF_AVAILABILITY_CALENDARS: [CALENDAR, "calendar.gone"]})
    client = await hass_client_no_auth()

    resp = await client.get(f"/api/webhook/{CALENDAR_WEBHOOK_ID}")
    assert resp.status == HTTPStatus.OK
    assert (await resp.text()).count("BEGIN:VEVENT") == 2


async def test_feed_disabled(hass: HomeAssistant, hass_client_no_auth) -> None:
    """Test the feed is off without selected calendars."""
    calls = _mock_calendar(hass, EVENTS)
    await _setup(hass)
    client = await hass_client_no_auth()

    resp = await client.get(f"/api/webhook/{CALENDAR_WEBHOOK_ID}")
    assert resp.status == HTTPStatus.OK
    assert "VCALENDAR" not in await resp.text()
    assert not calls


async def test_calendar_webhook_id_migration(hass: HomeAssistant) -> None:
    """Test entries without a feed URL get one on setup."""
    await async_setup_component(hass, "http", {})
    entry = MockConfigEntry(
        domain=DOMAIN, title="Feuerwehr", data={CONF_WEBHOOK_ID: WEBHOOK_ID}
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.minor_version == 3
    assert entry.data[CONF_WEBHOOK_ID] == WEBHOOK_ID
    assert entry.data[CONF_CALENDAR_WEBHOOK_ID]


async def test_options_flow_calendars(hass: HomeAssistant, hass_client_no_auth) -> None:
    """Test enabling the feed in the options."""
    _mock_calendar(hass, EVENTS)
    entry = await _setup(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["description_placeholders"]["calendar_url"].endswith(
        f"/api/webhook/{CALENDAR_WEBHOOK_ID}"
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_AVAILABILITY_CALENDARS: [CALENDAR],
            CONF_AVAILABILITY_KEYWORDS: [" Urlaub ", ""],
        },
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_AVAILABILITY_CALENDARS] == [CALENDAR]
    assert entry.options[CONF_AVAILABILITY_KEYWORDS] == ["Urlaub"]

    client = await hass_client_no_auth()
    resp = await client.get(f"/api/webhook/{CALENDAR_WEBHOOK_ID}")
    assert resp.content_type == "text/calendar"


def test_fold_long_lines() -> None:
    """Test long lines are folded after 75 octets without splitting characters."""
    line = "SUMMARY:" + "ä" * 100
    folded = _fold(line)
    parts = folded.split("\r\n")
    assert len(parts) > 1
    assert all(len(part.encode()) <= 75 for part in parts)
    assert parts[0] + "".join(part[1:] for part in parts[1:]) == line


def test_naive_datetime_uses_local_time_zone() -> None:
    """Test times without an offset are taken as local time."""
    dt_util.set_default_time_zone(dt_util.get_time_zone("Europe/Berlin"))
    try:
        body = build_ical(
            [
                (
                    CALENDAR,
                    {"start": "2026-07-01T10:00:00", "end": "2026-07-01T11:00:00"},
                )
            ],
            datetime(2026, 6, 1, tzinfo=dt_util.UTC),
            "Test",
        )
    finally:
        dt_util.set_default_time_zone(dt_util.UTC)
    assert "DTSTART:20260701T080000Z\r\n" in body
