"""Tests for the Alamos integration."""

from datetime import timedelta
from http import HTTPStatus

import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_capture_events,
    async_fire_time_changed,
)

from custom_components.alamos.const import (
    CONF_API_KEY,
    CONF_CLEAR_WEBHOOK_ID,
    CONF_RESET_MINUTES,
    CONF_TEST_KEYWORDS,
    CONF_UNIT_FILTER,
    CONF_WEBHOOK_ID,
    DEFAULT_API_URL,
    DOMAIN,
    EVENT_ALARM,
    EVENT_ALARM_CLEARED,
    FEEDBACK_PATH,
)
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import HomeAssistantError
from homeassistant.setup import async_setup_component

WEBHOOK_ID = "test_webhook"
CLEAR_WEBHOOK_ID = "test_clear_webhook"
FEEDBACK_URL = f"{DEFAULT_API_URL}{FEEDBACK_PATH}"


async def _setup(hass: HomeAssistant, api_key: str = "secret") -> MockConfigEntry:
    await async_setup_component(hass, "http", {})
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Feuerwehr",
        data={CONF_WEBHOOK_ID: WEBHOOK_ID, CONF_CLEAR_WEBHOOK_ID: CLEAR_WEBHOOK_ID},
        options={CONF_API_KEY: api_key, CONF_RESET_MINUTES: 30},
        minor_version=2,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_config_flow(hass: HomeAssistant) -> None:
    """Test the user flow creates an entry with a webhook."""
    await async_setup_component(hass, "http", {})
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"name": "Feuerwehr", "api_key": " abc "}
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Feuerwehr"
    assert result["data"][CONF_WEBHOOK_ID]
    assert result["data"][CONF_CLEAR_WEBHOOK_ID]
    assert result["data"][CONF_CLEAR_WEBHOOK_ID] != result["data"][CONF_WEBHOOK_ID]
    placeholders = result["description_placeholders"]
    assert placeholders["webhook_clear_url"].endswith(
        result["data"][CONF_CLEAR_WEBHOOK_ID]
    )
    assert result["options"][CONF_API_KEY] == "abc"
    assert "webhook_url" in result["description_placeholders"]


async def test_options_flow(hass: HomeAssistant) -> None:
    """Test the options flow removes the API key and buttons."""
    entry = await _setup(hass)
    assert hass.states.get("button.feuerwehr_accept_alarm")

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"api_key": "", "reset_minutes": 5}
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_API_KEY] == ""
    assert entry.runtime_data.client is None


async def test_webhook_get_and_clear(hass: HomeAssistant, hass_client_no_auth) -> None:
    """Test a GET webhook (AMweb / aPager PRO) and the clear URL."""
    await _setup(hass)
    alarms = async_capture_events(hass, EVENT_ALARM)
    cleared = async_capture_events(hass, EVENT_ALARM_CLEARED)
    client = await hass_client_no_auth()

    resp = await client.get(
        f"/api/webhook/{WEBHOOK_ID}", params={"keyword": "B3 Wohnung", "unit": "LZ1"}
    )
    assert resp.status == HTTPStatus.OK
    await hass.async_block_till_done()

    assert hass.states.get("binary_sensor.feuerwehr_alarm").state == "on"
    assert hass.states.get("sensor.feuerwehr_keyword").state == "B3 Wohnung"
    assert hass.states.get("sensor.feuerwehr_unit").state == "LZ1"
    assert hass.states.get("sensor.feuerwehr_alarm_count").state == "1"
    event_state = hass.states.get("event.feuerwehr_alarm_event")
    assert event_state.attributes["event_type"] == "alarm"
    assert len(alarms) == 1
    assert alarms[0].data["keyword"] == "B3 Wohnung"

    resp = await client.get(f"/api/webhook/{WEBHOOK_ID}?event=clear")
    assert resp.status == HTTPStatus.OK
    await hass.async_block_till_done()
    assert hass.states.get("binary_sensor.feuerwehr_alarm").state == "off"
    assert len(cleared) == 1


async def test_webhook_post_json(hass: HomeAssistant, hass_client_no_auth) -> None:
    """Test a POST webhook with a JSON body (aPager PRO)."""
    await _setup(hass)
    client = await hass_client_no_auth()
    resp = await client.post(
        f"/api/webhook/{WEBHOOK_ID}",
        json={"keyword": "THL 1", "unit": "Florian 1", "extra": 1},
    )
    assert resp.status == HTTPStatus.OK
    await hass.async_block_till_done()
    state = hass.states.get("binary_sensor.feuerwehr_alarm")
    assert state.state == "on"
    assert state.attributes["data"]["extra"] == 1
    assert hass.states.get("sensor.feuerwehr_keyword").state == "THL 1"


async def test_send_feedback(hass: HomeAssistant, aioclient_mock) -> None:
    """Test the feedback service and buttons."""
    await _setup(hass)
    aioclient_mock.get(FEEDBACK_URL, status=200)

    response = await hass.services.async_call(
        DOMAIN,
        "send_feedback",
        {"mode": "accept", "suppress_notification": True},
        blocking=True,
        return_response=True,
    )
    assert response["results"][0]["result"] == "success"
    _, url, _, _ = aioclient_mock.mock_calls[0]
    assert url.query["authToken"] == "secret"
    assert url.query["mode"] == "accept"
    assert url.query["suppressNotification"] == "true"
    assert hass.states.get("sensor.feuerwehr_last_feedback").state == "success"

    aioclient_mock.clear_requests()
    aioclient_mock.get(FEEDBACK_URL, status=204)
    await hass.services.async_call(
        "button", "press", {"entity_id": "button.feuerwehr_reject_alarm"}, blocking=True
    )
    assert aioclient_mock.mock_calls[0][1].query["mode"] == "reject"
    assert hass.states.get("sensor.feuerwehr_last_feedback").state == "no_alarm"


async def test_send_feedback_invalid_key(hass: HomeAssistant, aioclient_mock) -> None:
    """Test a 403 response raises an error."""
    await _setup(hass)
    aioclient_mock.get(FEEDBACK_URL, status=403)
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            DOMAIN, "send_feedback", {"mode": "accept"}, blocking=True
        )
    assert hass.states.get("sensor.feuerwehr_last_feedback").state == "invalid_api_key"


async def test_without_api_key(hass: HomeAssistant) -> None:
    """Test that no buttons are created without an API key."""
    await _setup(hass, api_key="")
    assert hass.states.get("button.feuerwehr_accept_alarm") is None
    assert hass.states.get("binary_sensor.feuerwehr_alarm")


async def test_unload(hass: HomeAssistant) -> None:
    """Test unloading the entry."""
    entry = await _setup(hass)
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def test_auto_reset(hass: HomeAssistant, hass_client_no_auth, freezer) -> None:
    """Test the alarm is reset automatically after the configured time."""
    await _setup(hass)
    client = await hass_client_no_auth()
    await client.get(f"/api/webhook/{WEBHOOK_ID}", params={"keyword": "F1"})
    await hass.async_block_till_done()
    assert hass.states.get("binary_sensor.feuerwehr_alarm").state == "on"

    freezer.tick(timedelta(minutes=31))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass.states.get("binary_sensor.feuerwehr_alarm").state == "off"


async def test_unit_filter(hass: HomeAssistant, hass_client_no_auth) -> None:
    """Alarms of other units are ignored, alarms without unit are accepted."""
    entry = await _setup(hass)
    hass.config_entries.async_update_entry(
        entry, options={**entry.options, CONF_UNIT_FILTER: ["LZ1", "lz2"]}
    )
    await hass.async_block_till_done()
    alarms = async_capture_events(hass, EVENT_ALARM)
    client = await hass_client_no_auth()

    resp = await client.get(
        f"/api/webhook/{WEBHOOK_ID}", params={"keyword": "F1", "unit": "LZ3"}
    )
    assert await resp.text() == "ignored"
    await hass.async_block_till_done()
    assert alarms == []
    assert hass.states.get("binary_sensor.feuerwehr_alarm").state == "off"

    await client.get(
        f"/api/webhook/{WEBHOOK_ID}", params={"keyword": "F1", "unit": "LZ2"}
    )
    await client.get(f"/api/webhook/{WEBHOOK_ID}", params={"keyword": "F2"})
    await hass.async_block_till_done()
    assert [event.data["unit"] for event in alarms] == ["LZ2", None]


async def test_test_alarm(hass: HomeAssistant, hass_client_no_auth) -> None:
    """Test alarms fire events but do not activate the alarm sensor."""
    entry = await _setup(hass)
    hass.config_entries.async_update_entry(
        entry, options={**entry.options, CONF_TEST_KEYWORDS: ["probealarm"]}
    )
    await hass.async_block_till_done()
    alarms = async_capture_events(hass, EVENT_ALARM)
    client = await hass_client_no_auth()

    resp = await client.get(
        f"/api/webhook/{WEBHOOK_ID}", params={"keyword": "Probealarm Sirene"}
    )
    assert await resp.text() == "test"
    await hass.async_block_till_done()

    assert len(alarms) == 1
    assert alarms[0].data["test"] is True
    assert hass.states.get("binary_sensor.feuerwehr_alarm").state == "off"
    assert hass.states.get("sensor.feuerwehr_alarm_count").state == "0"
    event_state = hass.states.get("event.feuerwehr_alarm_event")
    assert event_state.attributes["event_type"] == "test_alarm"


async def test_feedback_deadline(
    hass: HomeAssistant, hass_client_no_auth, freezer
) -> None:
    """The feedback deadline is three minutes after the alarm."""
    freezer.move_to("2026-10-07 18:00:00+00:00")
    await _setup(hass)
    alarms = async_capture_events(hass, EVENT_ALARM)
    client = await hass_client_no_auth()
    await client.get(f"/api/webhook/{WEBHOOK_ID}", params={"keyword": "F1"})
    await hass.async_block_till_done()

    expected = "2026-10-07T18:03:00+00:00"
    assert alarms[0].data["feedback_deadline"] == expected
    assert alarms[0].data["test"] is False
    state = hass.states.get("binary_sensor.feuerwehr_alarm")
    assert state.attributes["feedback_deadline"] == expected


async def test_options_flow_lists(hass: HomeAssistant) -> None:
    """List options are stripped and empty items removed."""
    entry = await _setup(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "api_key": "secret",
            "unit_filter": [" LZ1 ", ""],
            "test_keywords": ["Probealarm", "  "],
        },
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_UNIT_FILTER] == ["LZ1"]
    assert entry.options[CONF_TEST_KEYWORDS] == ["Probealarm"]


async def test_recall_webhook(hass: HomeAssistant, hass_client_no_auth) -> None:
    """The separate recall webhook clears the alarm and reports the recall."""
    await _setup(hass)
    cleared = async_capture_events(hass, EVENT_ALARM_CLEARED)
    client = await hass_client_no_auth()

    await client.get(f"/api/webhook/{WEBHOOK_ID}", params={"keyword": "F2"})
    await hass.async_block_till_done()
    assert hass.states.get("binary_sensor.feuerwehr_alarm").state == "on"

    resp = await client.post(
        f"/api/webhook/{CLEAR_WEBHOOK_ID}", json={"keyword": "F2", "unit": "LZ1"}
    )
    assert resp.status == HTTPStatus.OK
    assert await resp.text() == "cleared"
    await hass.async_block_till_done()

    assert hass.states.get("binary_sensor.feuerwehr_alarm").state == "off"
    assert len(cleared) == 1
    assert cleared[0].data["recall"] is True
    assert cleared[0].data["keyword"] == "F2"
    assert cleared[0].data["unit"] == "LZ1"
    event_state = hass.states.get("event.feuerwehr_alarm_event")
    assert event_state.attributes["event_type"] == "cleared"
    assert event_state.attributes["recall"] is True

    # A recall is always reported, even if no alarm is active (anymore).
    resp = await client.get(f"/api/webhook/{CLEAR_WEBHOOK_ID}")
    assert resp.status == HTTPStatus.OK
    await hass.async_block_till_done()
    assert len(cleared) == 2
    # The recall webhook never triggers an alarm.
    assert hass.states.get("binary_sensor.feuerwehr_alarm").state == "off"
    assert hass.states.get("sensor.feuerwehr_alarm_count").state == "1"


async def test_recall_webhook_unit_filter(
    hass: HomeAssistant, hass_client_no_auth
) -> None:
    """Recalls of other units do not end the alarm."""
    entry = await _setup(hass)
    hass.config_entries.async_update_entry(
        entry, options={**entry.options, CONF_UNIT_FILTER: ["LZ1"]}
    )
    await hass.async_block_till_done()
    cleared = async_capture_events(hass, EVENT_ALARM_CLEARED)
    client = await hass_client_no_auth()

    await client.get(f"/api/webhook/{WEBHOOK_ID}", params={"unit": "LZ1"})
    resp = await client.get(f"/api/webhook/{CLEAR_WEBHOOK_ID}", params={"unit": "LZ9"})
    assert await resp.text() == "ignored"
    await hass.async_block_till_done()
    assert hass.states.get("binary_sensor.feuerwehr_alarm").state == "on"
    assert not cleared

    resp = await client.get(f"/api/webhook/{CLEAR_WEBHOOK_ID}", params={"unit": "lz1"})
    assert await resp.text() == "cleared"
    await hass.async_block_till_done()
    assert hass.states.get("binary_sensor.feuerwehr_alarm").state == "off"
    assert len(cleared) == 1


async def test_migrate_adds_recall_webhook(
    hass: HomeAssistant, hass_client_no_auth
) -> None:
    """Existing entries get a recall webhook on update."""
    await async_setup_component(hass, "http", {})
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Feuerwehr",
        data={CONF_WEBHOOK_ID: WEBHOOK_ID},
        options={CONF_API_KEY: "", CONF_RESET_MINUTES: 30},
        version=1,
        minor_version=1,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.minor_version == 2
    assert entry.data[CONF_WEBHOOK_ID] == WEBHOOK_ID
    clear_webhook_id = entry.data[CONF_CLEAR_WEBHOOK_ID]
    assert clear_webhook_id and clear_webhook_id != WEBHOOK_ID

    client = await hass_client_no_auth()
    await client.get(f"/api/webhook/{WEBHOOK_ID}", params={"keyword": "F1"})
    await hass.async_block_till_done()
    assert hass.states.get("binary_sensor.feuerwehr_alarm").state == "on"
    await client.get(f"/api/webhook/{clear_webhook_id}")
    await hass.async_block_till_done()
    assert hass.states.get("binary_sensor.feuerwehr_alarm").state == "off"
