"""Tests for the Alamos integration."""

from datetime import timedelta
from http import HTTPStatus

import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_capture_events,
    async_fire_time_changed,
    mock_restore_cache_with_extra_data,
)
import voluptuous as vol

from custom_components.alamos import entry_webhook_ids
from custom_components.alamos.const import (
    CONF_ADDITIONAL_WEBHOOK_IDS,
    CONF_API_KEY,
    CONF_API_URL,
    CONF_FAVORITE_UNIT,
    CONF_RESET_MINUTES,
    CONF_TEST_KEYWORDS,
    CONF_UNIT_FILTER,
    CONF_WEBHOOK_COUNT,
    CONF_WEBHOOK_ID,
    DEFAULT_API_URL,
    DOMAIN,
    EVENT_ALARM,
    EVENT_ALARM_CLEARED,
    FEEDBACK_PATH,
)
from homeassistant import config_entries
from homeassistant.core import HomeAssistant, State
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import entity_registry as er, issue_registry as ir
from homeassistant.setup import async_setup_component

WEBHOOK_ID = "test_webhook"
FEEDBACK_URL = f"{DEFAULT_API_URL}{FEEDBACK_PATH}"


async def _setup(
    hass: HomeAssistant, api_key: str = "secret", **options
) -> MockConfigEntry:
    await async_setup_component(hass, "http", {})
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Feuerwehr",
        data={CONF_WEBHOOK_ID: WEBHOOK_ID},
        options={CONF_API_KEY: api_key, CONF_RESET_MINUTES: 30, **options},
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
    assert result["options"][CONF_API_KEY] == "abc"
    assert "webhook_url" in result["description_placeholders"]
    assert result["description_placeholders"]["webhook_recall_url"].endswith(
        "?event=recall"
    )


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


async def _setup_second_entry(hass: HomeAssistant, api_key: str) -> MockConfigEntry:
    """Set up a second profile, e.g. for a double membership."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Rettungsdienst",
        data={CONF_WEBHOOK_ID: "second_webhook"},
        options={CONF_API_KEY: api_key},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_send_feedback_one_entry_fails(
    hass: HomeAssistant, aioclient_mock
) -> None:
    """A failing entry does not keep the other entries from answering."""
    first = await _setup(hass)
    second = await _setup_second_entry(hass, "other")
    aioclient_mock.get(f"{FEEDBACK_URL}?authToken=other", status=403)
    aioclient_mock.get(f"{FEEDBACK_URL}?authToken=secret", status=200)

    response = await hass.services.async_call(
        DOMAIN, "send_feedback", {"mode": "accept"}, blocking=True, return_response=True
    )
    results = {result["config_entry_id"]: result for result in response["results"]}
    assert results[first.entry_id]["result"] == "success"
    assert results[first.entry_id]["status"] == 200
    assert results[second.entry_id]["result"] == "invalid_api_key"
    assert results[second.entry_id]["status"] is None
    assert results[second.entry_id]["error"]
    assert hass.states.get("sensor.feuerwehr_last_feedback").state == "success"
    assert (
        hass.states.get("sensor.rettungsdienst_last_feedback").state
        == "invalid_api_key"
    )


async def test_send_feedback_all_entries_fail(
    hass: HomeAssistant, aioclient_mock
) -> None:
    """The service only fails if no entry could answer."""
    await _setup(hass)
    await _setup_second_entry(hass, "other")
    aioclient_mock.get(FEEDBACK_URL, status=409)
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            DOMAIN, "send_feedback", {"mode": "accept"}, blocking=True
        )
    assert hass.states.get("sensor.feuerwehr_last_feedback").state == "no_subscription"
    assert (
        hass.states.get("sensor.rettungsdienst_last_feedback").state
        == "no_subscription"
    )


async def test_send_feedback_without_api_key_names_entry(
    hass: HomeAssistant,
) -> None:
    """The error for a missing API key names the entry."""
    entry = await _setup(hass, api_key="")
    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(
            DOMAIN,
            "send_feedback",
            {"mode": "accept", "config_entry_id": entry.entry_id},
            blocking=True,
        )
    assert err.value.translation_placeholders == {"name": "Feuerwehr"}


async def test_insecure_api_url_issue(hass: HomeAssistant) -> None:
    """An http:// API URL raises a repair issue until it is changed."""
    entry = await _setup(hass, **{CONF_API_URL: "http://fe2.local"})
    issue_id = f"insecure_api_url_{entry.entry_id}"
    registry = ir.async_get(hass)
    issue = registry.async_get_issue(DOMAIN, issue_id)
    assert issue.severity is ir.IssueSeverity.WARNING
    assert issue.translation_placeholders["url"] == "http://fe2.local"
    assert entry.runtime_data.client is not None

    hass.config_entries.async_update_entry(
        entry, options={**entry.options, CONF_API_URL: "https://fe2.local"}
    )
    await hass.async_block_till_done()
    assert registry.async_get_issue(DOMAIN, issue_id) is None

    # Without an API key nothing is sent, so there is nothing to warn about.
    hass.config_entries.async_update_entry(
        entry, options={CONF_API_KEY: "", CONF_API_URL: "http://fe2.local"}
    )
    await hass.async_block_till_done()
    assert registry.async_get_issue(DOMAIN, issue_id) is None


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
            "favorite_unit": " LZ2 ",
        },
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_UNIT_FILTER] == ["LZ1"]
    assert entry.options[CONF_TEST_KEYWORDS] == ["Probealarm"]
    assert entry.options[CONF_FAVORITE_UNIT] == "LZ2"


async def test_webhook_recall(hass: HomeAssistant, hass_client_no_auth) -> None:
    """A recall ends the alarm and is always reported with its data."""
    await _setup(hass)
    cleared = async_capture_events(hass, EVENT_ALARM_CLEARED)
    client = await hass_client_no_auth()

    await client.get(f"/api/webhook/{WEBHOOK_ID}", params={"keyword": "F2"})
    await hass.async_block_till_done()
    assert hass.states.get("binary_sensor.feuerwehr_alarm").state == "on"

    resp = await client.post(
        f"/api/webhook/{WEBHOOK_ID}?event=recall", json={"keyword": "F2", "unit": "LZ1"}
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

    # A recall is reported even if no alarm is active (anymore), and the
    # event parameter may also be part of the JSON body.
    resp = await client.post(f"/api/webhook/{WEBHOOK_ID}", json={"event": "cancel"})
    assert await resp.text() == "cleared"
    await hass.async_block_till_done()
    assert len(cleared) == 2
    assert hass.states.get("binary_sensor.feuerwehr_alarm").state == "off"
    assert hass.states.get("sensor.feuerwehr_alarm_count").state == "1"

    # A plain clear without an active alarm stays silent.
    await client.get(f"/api/webhook/{WEBHOOK_ID}?event=clear")
    await hass.async_block_till_done()
    assert len(cleared) == 2


async def test_webhook_recall_unit_filter(
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
    url = f"/api/webhook/{WEBHOOK_ID}"

    await client.get(url, params={"unit": "LZ1"})
    resp = await client.get(url, params={"event": "recall", "unit": "LZ9"})
    assert await resp.text() == "ignored"
    await hass.async_block_till_done()
    assert hass.states.get("binary_sensor.feuerwehr_alarm").state == "on"
    assert not cleared

    resp = await client.get(url, params={"event": "recall", "unit": "lz1"})
    assert await resp.text() == "cleared"
    await hass.async_block_till_done()
    assert hass.states.get("binary_sensor.feuerwehr_alarm").state == "off"
    assert len(cleared) == 1


async def test_webhooks_per_unit_are_merged(
    hass: HomeAssistant, hass_client_no_auth, freezer
) -> None:
    """aPager PRO sends one webhook per alarmed unit; they form one alarm."""
    await _setup(hass)
    alarms = async_capture_events(hass, EVENT_ALARM)
    client = await hass_client_no_auth()
    url = f"/api/webhook/{WEBHOOK_ID}"

    resp = await client.post(url, json={"keyword": "B3", "unit": "LZ1"})
    assert await resp.text() == "ok"
    freezer.tick(timedelta(seconds=5))
    resp = await client.post(url, json={"keyword": "b3", "unit": "LZ2"})
    assert await resp.text() == "merged"
    resp = await client.post(url, json={"keyword": "B3", "unit": "LZ1"})
    assert await resp.text() == "merged"
    await hass.async_block_till_done()

    assert len(alarms) == 1
    assert alarms[0].data["units"] == ["LZ1"]
    state = hass.states.get("binary_sensor.feuerwehr_alarm")
    assert state.attributes["units"] == ["LZ1", "LZ2"]
    assert state.attributes["unit"] == "LZ1"
    assert hass.states.get("sensor.feuerwehr_alarm_count").state == "1"

    # A different keyword or a later webhook is a new alarm.
    resp = await client.post(url, json={"keyword": "THL", "unit": "LZ1"})
    assert await resp.text() == "ok"
    freezer.tick(timedelta(seconds=31))
    resp = await client.post(url, json={"keyword": "THL", "unit": "LZ1"})
    assert await resp.text() == "ok"
    await hass.async_block_till_done()
    assert len(alarms) == 3
    assert hass.states.get("sensor.feuerwehr_alarm_count").state == "3"


async def test_repeated_test_alarm_and_recall(
    hass: HomeAssistant, hass_client_no_auth
) -> None:
    """Test alarms and recalls of several units are reported once."""
    entry = await _setup(hass)
    hass.config_entries.async_update_entry(
        entry, options={**entry.options, CONF_TEST_KEYWORDS: ["probealarm"]}
    )
    await hass.async_block_till_done()
    alarms = async_capture_events(hass, EVENT_ALARM)
    cleared = async_capture_events(hass, EVENT_ALARM_CLEARED)
    client = await hass_client_no_auth()
    url = f"/api/webhook/{WEBHOOK_ID}"

    for unit in ("LZ1", "LZ2"):
        await client.get(url, params={"keyword": "Probealarm", "unit": unit})
        await client.get(url, params={"event": "recall", "keyword": "F2", "unit": unit})
    await hass.async_block_till_done()

    assert len(alarms) == 1
    assert alarms[0].data["test"] is True
    assert len(cleared) == 1


async def test_webhook_without_keyword_is_merged(
    hass: HomeAssistant, hass_client_no_auth
) -> None:
    """A unit webhook without keyword does not start a new alarm."""
    await _setup(hass)
    alarms = async_capture_events(hass, EVENT_ALARM)
    client = await hass_client_no_auth()
    url = f"/api/webhook/{WEBHOOK_ID}"

    resp = await client.get(url, params={"keyword": "BMA", "unit": "LZ1"})
    assert await resp.text() == "ok"
    resp = await client.get(url, params={"unit": "LZ2"})
    assert await resp.text() == "merged"
    await hass.async_block_till_done()

    assert len(alarms) == 1
    assert hass.states.get("sensor.feuerwehr_keyword").state == "BMA"
    assert hass.states.get("sensor.feuerwehr_unit").state == "LZ1, LZ2"
    state = hass.states.get("binary_sensor.feuerwehr_alarm")
    assert state.attributes["keyword"] == "BMA"
    assert state.attributes["units"] == ["LZ1", "LZ2"]


async def test_keyword_of_later_webhook_fills_gap(
    hass: HomeAssistant, hass_client_no_auth
) -> None:
    """The keyword is taken from a later unit webhook if the first had none."""
    await _setup(hass)
    alarms = async_capture_events(hass, EVENT_ALARM)
    client = await hass_client_no_auth()
    url = f"/api/webhook/{WEBHOOK_ID}"

    await client.get(url, params={"unit": "LZ1"})
    resp = await client.get(url, params={"keyword": "BMA", "unit": "LZ2"})
    assert await resp.text() == "merged"
    await hass.async_block_till_done()

    assert len(alarms) == 1
    assert hass.states.get("sensor.feuerwehr_keyword").state == "BMA"


async def test_favorite_unit(hass: HomeAssistant, hass_client_no_auth) -> None:
    """The favorite unit is always listed first and becomes the main unit."""
    entry = await _setup(hass)
    hass.config_entries.async_update_entry(
        entry, options={**entry.options, CONF_FAVORITE_UNIT: "lz2"}
    )
    await hass.async_block_till_done()
    client = await hass_client_no_auth()
    url = f"/api/webhook/{WEBHOOK_ID}"

    for unit in ("LZ1", "DLK", "LZ2"):
        await client.get(url, params={"keyword": "B3", "unit": unit})
    await hass.async_block_till_done()

    unit_sensor = hass.states.get("sensor.feuerwehr_unit")
    assert unit_sensor.state == "LZ2, LZ1, DLK"
    assert unit_sensor.attributes["unit"] == "LZ2"
    assert unit_sensor.attributes["units"] == ["LZ2", "LZ1", "DLK"]
    state = hass.states.get("binary_sensor.feuerwehr_alarm")
    assert state.attributes["unit"] == "LZ2"
    assert state.attributes["units"] == ["LZ2", "LZ1", "DLK"]


async def test_last_webhook_sensor(hass: HomeAssistant, hass_client_no_auth) -> None:
    """Every webhook call is recorded, including merged and ignored ones."""
    entry = await _setup(hass)
    hass.config_entries.async_update_entry(
        entry, options={**entry.options, CONF_UNIT_FILTER: ["LZ1"]}
    )
    await hass.async_block_till_done()
    client = await hass_client_no_auth()
    url = f"/api/webhook/{WEBHOOK_ID}"

    await client.post(url, json={"keyword": "BMA", "unit": "LZ1"})
    await hass.async_block_till_done()
    state = hass.states.get("sensor.feuerwehr_last_webhook")
    assert state.attributes["method"] == "POST"
    assert state.attributes["result"] == "ok"
    assert state.attributes["data"] == {"keyword": "BMA", "unit": "LZ1"}
    first = state.attributes["received"]

    await client.get(url, params={"keyword": "", "unit": "LZ1"})
    await hass.async_block_till_done()
    state = hass.states.get("sensor.feuerwehr_last_webhook")
    assert state.attributes["received"] != first
    assert state.attributes["result"] == "merged"
    assert state.attributes["data"] == {"keyword": "", "unit": "LZ1"}

    await client.get(url, params={"event": "recall", "unit": "LZ9"})
    await hass.async_block_till_done()
    state = hass.states.get("sensor.feuerwehr_last_webhook")
    assert state.attributes["result"] == "ignored"
    assert state.attributes["data"] == {"event": "recall", "unit": "LZ9"}


async def test_migration_adds_webhooks(hass: HomeAssistant) -> None:
    """Entries from before multiple webhooks get the additional webhook IDs."""
    entry = await _setup(hass)
    assert entry.minor_version == 2
    assert entry.data[CONF_WEBHOOK_ID] == WEBHOOK_ID
    assert len(set(entry.data[CONF_ADDITIONAL_WEBHOOK_IDS])) == 4
    assert not hass.states.get("sensor.feuerwehr_alarm_count_webhook_1")


async def test_multiple_webhooks(hass: HomeAssistant, hass_client_no_auth) -> None:
    """Every webhook counts its alarms, the alarm count counts each alarm once."""
    entry = await _setup(hass, **{CONF_WEBHOOK_COUNT: 3})
    alarms = async_capture_events(hass, EVENT_ALARM)
    client = await hass_client_no_auth()
    urls = [f"/api/webhook/{webhook_id}" for webhook_id in entry_webhook_ids(entry)]

    resp = await client.get(urls[0], params={"keyword": "B3", "unit": "LZ1"})
    assert await resp.text() == "ok"
    resp = await client.get(urls[1], params={"keyword": "B3", "unit": "RD"})
    assert await resp.text() == "merged"
    resp = await client.get(urls[1], params={"keyword": "B3", "unit": "RD2"})
    assert await resp.text() == "merged"
    await hass.async_block_till_done()

    assert len(alarms) == 1
    assert alarms[0].data["webhook"] == 1
    assert hass.states.get("binary_sensor.feuerwehr_alarm").attributes["units"] == [
        "LZ1",
        "RD",
        "RD2",
    ]
    assert hass.states.get("sensor.feuerwehr_alarm_count_webhook_1").state == "1"
    assert hass.states.get("sensor.feuerwehr_alarm_count_webhook_2").state == "1"
    assert hass.states.get("sensor.feuerwehr_alarm_count_webhook_3").state == "0"
    assert not hass.states.get("sensor.feuerwehr_alarm_count_webhook_4")
    assert hass.states.get("sensor.feuerwehr_alarm_count").state == "1"

    resp = await client.get(urls[2], params={"keyword": "THL", "unit": "LZ3"})
    assert await resp.text() == "ok"
    await hass.async_block_till_done()
    assert alarms[1].data["webhook"] == 3
    assert hass.states.get("sensor.feuerwehr_alarm_count_webhook_3").state == "1"
    assert hass.states.get("sensor.feuerwehr_alarm_count").state == "2"
    last = hass.states.get("sensor.feuerwehr_last_webhook")
    assert last.attributes["webhook"] == 3

    await client.get(f"{urls[2]}?event=clear")
    await hass.async_block_till_done()
    assert hass.states.get("binary_sensor.feuerwehr_alarm").state == "off"


async def test_uncounted_webhooks_stay_active(
    hass: HomeAssistant, hass_client_no_auth
) -> None:
    """A webhook beyond the configured number still raises the alarm."""
    entry = await _setup(hass)
    alarms = async_capture_events(hass, EVENT_ALARM)
    client = await hass_client_no_auth()

    resp = await client.get(
        f"/api/webhook/{entry_webhook_ids(entry)[4]}", params={"keyword": "B3"}
    )
    assert await resp.text() == "ok"
    await hass.async_block_till_done()
    assert alarms[0].data["webhook"] == 5
    assert hass.states.get("binary_sensor.feuerwehr_alarm").state == "on"
    assert hass.states.get("sensor.feuerwehr_alarm_count").state == "1"


async def test_options_show_all_webhooks(hass: HomeAssistant) -> None:
    """The options always list the URLs of all webhooks."""
    entry = await _setup(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    additional = result["description_placeholders"]["additional_webhooks"]
    for number, webhook_id in enumerate(entry_webhook_ids(entry)[1:], start=2):
        assert f"Webhook {number}" in additional
        assert webhook_id in additional


async def test_webhook_count_sensors_are_removed(hass: HomeAssistant) -> None:
    """Count sensors of webhooks which are not counted anymore are removed."""
    entry = await _setup(hass, **{CONF_WEBHOOK_COUNT: 3})
    registry = er.async_get(hass)
    assert registry.async_get("sensor.feuerwehr_alarm_count_webhook_3")

    hass.config_entries.async_update_entry(
        entry, options={**entry.options, CONF_WEBHOOK_COUNT: 2}
    )
    await hass.async_block_till_done()
    assert registry.async_get("sensor.feuerwehr_alarm_count_webhook_2")
    assert not registry.async_get("sensor.feuerwehr_alarm_count_webhook_3")

    hass.config_entries.async_update_entry(
        entry, options={**entry.options, CONF_WEBHOOK_COUNT: 1}
    )
    await hass.async_block_till_done()
    assert not registry.async_get("sensor.feuerwehr_alarm_count_webhook_1")
    assert not registry.async_get("sensor.feuerwehr_alarm_count_webhook_2")


async def test_restore_counts(hass: HomeAssistant) -> None:
    """The alarm count and the webhook counts survive a restart."""
    mock_restore_cache_with_extra_data(
        hass,
        [
            (
                State("sensor.feuerwehr_alarm_count", "7"),
                {"native_value": 7, "native_unit_of_measurement": None},
            ),
            (
                State("sensor.feuerwehr_alarm_count_webhook_2", "2"),
                {"native_value": 2, "native_unit_of_measurement": None},
            ),
        ],
    )
    await _setup(hass, **{CONF_WEBHOOK_COUNT: 2})

    assert hass.states.get("sensor.feuerwehr_alarm_count").state == "7"
    assert hass.states.get("sensor.feuerwehr_alarm_count_webhook_1").state == "0"
    assert hass.states.get("sensor.feuerwehr_alarm_count_webhook_2").state == "2"


async def test_reset_alarm_count(hass: HomeAssistant, hass_client_no_auth) -> None:
    """The button resets the alarm count and all webhook counts."""
    entry = await _setup(hass, api_key="", **{CONF_WEBHOOK_COUNT: 2})
    client = await hass_client_no_auth()
    for webhook_id in entry_webhook_ids(entry)[:2]:
        await client.get(f"/api/webhook/{webhook_id}", params={"keyword": "B3"})
    await hass.async_block_till_done()
    assert hass.states.get("sensor.feuerwehr_alarm_count").state == "1"
    assert hass.states.get("sensor.feuerwehr_alarm_count_webhook_2").state == "1"

    await hass.services.async_call(
        "button",
        "press",
        {"entity_id": "button.feuerwehr_reset_alarm_count"},
        blocking=True,
    )
    assert hass.states.get("sensor.feuerwehr_alarm_count").state == "0"
    assert hass.states.get("sensor.feuerwehr_alarm_count_webhook_1").state == "0"
    assert hass.states.get("sensor.feuerwehr_alarm_count_webhook_2").state == "0"

    await client.get(f"/api/webhook/{WEBHOOK_ID}", params={"keyword": "THL"})
    await hass.async_block_till_done()
    assert hass.states.get("sensor.feuerwehr_alarm_count").state == "1"


async def test_reset_alarm_count_service(
    hass: HomeAssistant, hass_client_no_auth
) -> None:
    """The service resets one webhook count or all counts of an entry."""
    entry = await _setup(hass, **{CONF_WEBHOOK_COUNT: 2})
    client = await hass_client_no_auth()
    for webhook_id in entry_webhook_ids(entry)[:2]:
        await client.get(f"/api/webhook/{webhook_id}", params={"keyword": "B3"})
    await hass.async_block_till_done()

    await hass.services.async_call(
        DOMAIN, "reset_alarm_count", {"webhook": 2}, blocking=True
    )
    assert hass.states.get("sensor.feuerwehr_alarm_count").state == "1"
    assert hass.states.get("sensor.feuerwehr_alarm_count_webhook_1").state == "1"
    assert hass.states.get("sensor.feuerwehr_alarm_count_webhook_2").state == "0"

    await hass.services.async_call(
        DOMAIN,
        "reset_alarm_count",
        {"config_entry_id": entry.entry_id},
        blocking=True,
    )
    assert hass.states.get("sensor.feuerwehr_alarm_count").state == "0"
    assert hass.states.get("sensor.feuerwehr_alarm_count_webhook_1").state == "0"

    with pytest.raises(vol.Invalid):
        await hass.services.async_call(
            DOMAIN, "reset_alarm_count", {"webhook": 6}, blocking=True
        )


async def test_webhook_event_entities(
    hass: HomeAssistant, hass_client_no_auth, freezer
) -> None:
    """Every webhook has its own event entity, which fires for merged alarms too."""
    entry = await _setup(hass, **{CONF_WEBHOOK_COUNT: 2})
    alarms = async_capture_events(hass, EVENT_ALARM)
    client = await hass_client_no_auth()
    urls = [f"/api/webhook/{webhook_id}" for webhook_id in entry_webhook_ids(entry)]
    assert hass.states.get("event.feuerwehr_alarm_event_webhook_1").state == "unknown"

    await client.get(urls[0], params={"keyword": "B3", "unit": "LZ1"})
    resp = await client.get(urls[1], params={"unit": "RD"})
    assert await resp.text() == "merged"
    await hass.async_block_till_done()

    assert len(alarms) == 1
    first = hass.states.get("event.feuerwehr_alarm_event_webhook_1")
    assert first.attributes["event_type"] == "alarm"
    assert first.attributes["unit"] == "LZ1"
    second = hass.states.get("event.feuerwehr_alarm_event_webhook_2")
    assert second.attributes["event_type"] == "alarm"
    assert second.attributes["keyword"] == "B3"
    assert second.attributes["unit"] == "RD"
    assert second.attributes["webhook"] == 2

    freezer.tick(timedelta(seconds=1))
    await client.get(urls[1], params={"unit": "RD2"})
    await hass.async_block_till_done()
    assert hass.states.get("event.feuerwehr_alarm_event_webhook_2") == second

    await client.get(f"{urls[1]}?event=recall", params={"keyword": "B3"})
    await hass.async_block_till_done()
    for number in (1, 2):
        state = hass.states.get(f"event.feuerwehr_alarm_event_webhook_{number}")
        assert state.attributes["event_type"] == "cleared"
        assert state.attributes["recall"] is True

    first = hass.states.get("event.feuerwehr_alarm_event_webhook_1")
    await client.get(f"{urls[0]}?event=recall", params={"keyword": "B3"})
    await hass.async_block_till_done()
    assert hass.states.get("event.feuerwehr_alarm_event_webhook_1") == first


async def test_webhook_event_test_alarm_and_clear(
    hass: HomeAssistant, hass_client_no_auth
) -> None:
    """Test alarms reach every webhook once; a clear reaches the alarmed webhooks."""
    entry = await _setup(hass, **{CONF_WEBHOOK_COUNT: 2, CONF_TEST_KEYWORDS: ["Probe"]})
    alarms = async_capture_events(hass, EVENT_ALARM)
    client = await hass_client_no_auth()
    urls = [f"/api/webhook/{webhook_id}" for webhook_id in entry_webhook_ids(entry)]

    for url in urls[:2]:
        resp = await client.get(url, params={"keyword": "Probealarm"})
    assert await resp.text() == "merged"
    await hass.async_block_till_done()
    assert len(alarms) == 1
    for number in (1, 2):
        state = hass.states.get(f"event.feuerwehr_alarm_event_webhook_{number}")
        assert state.attributes["event_type"] == "test_alarm"

    await client.get(urls[0], params={"keyword": "BMA"})
    await client.get(f"{urls[1]}?event=clear")
    await hass.async_block_till_done()
    state = hass.states.get("event.feuerwehr_alarm_event_webhook_1")
    assert state.attributes["event_type"] == "cleared"
    state = hass.states.get("event.feuerwehr_alarm_event_webhook_2")
    assert state.attributes["event_type"] == "test_alarm"


async def test_webhook_event_cleared_on_reset(
    hass: HomeAssistant, hass_client_no_auth, freezer
) -> None:
    """The auto reset and the reset service clear every alarmed webhook."""
    entry = await _setup(hass, **{CONF_WEBHOOK_COUNT: 3, CONF_RESET_MINUTES: 5})
    client = await hass_client_no_auth()
    urls = [f"/api/webhook/{webhook_id}" for webhook_id in entry_webhook_ids(entry)]

    for url in urls[:2]:
        await client.get(url, params={"keyword": "B3"})
    freezer.tick(timedelta(minutes=6))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    for number in (1, 2):
        state = hass.states.get(f"event.feuerwehr_alarm_event_webhook_{number}")
        assert state.attributes["event_type"] == "cleared"
    assert hass.states.get("event.feuerwehr_alarm_event_webhook_3").state == "unknown"

    first = hass.states.get("event.feuerwehr_alarm_event_webhook_1")
    await client.get(urls[2], params={"keyword": "F2"})
    await hass.services.async_call(
        DOMAIN, "reset_alarm", {"config_entry_id": entry.entry_id}, blocking=True
    )
    state = hass.states.get("event.feuerwehr_alarm_event_webhook_3")
    assert state.attributes["event_type"] == "cleared"
    assert hass.states.get("event.feuerwehr_alarm_event_webhook_1") == first


async def test_webhook_event_entities_are_removed(hass: HomeAssistant) -> None:
    """Event entities of webhooks without their own entities are removed."""
    entry = await _setup(hass, **{CONF_WEBHOOK_COUNT: 2})
    registry = er.async_get(hass)
    assert registry.async_get("event.feuerwehr_alarm_event_webhook_2")

    hass.config_entries.async_update_entry(
        entry, options={**entry.options, CONF_WEBHOOK_COUNT: 1}
    )
    await hass.async_block_till_done()
    assert not registry.async_get("event.feuerwehr_alarm_event_webhook_1")
    assert not registry.async_get("event.feuerwehr_alarm_event_webhook_2")
    assert registry.async_get("event.feuerwehr_alarm_event")
