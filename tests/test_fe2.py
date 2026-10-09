"""Tests for the FE2 external interface actions."""

from http import HTTPStatus

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
import voluptuous as vol

from custom_components.alamos.const import (
    CONF_FE2_AUTHORIZATION,
    CONF_FE2_SENDER,
    CONF_FE2_URL,
    CONF_WEBHOOK_ID,
    DOMAIN,
)
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.setup import async_setup_component

FE2_URL = "http://fe2.local:83"
ALARM_URL = f"{FE2_URL}/rest/external/http/alarm/v2"
STATUS_URL = f"{FE2_URL}/rest/external/http/status/v2"


async def _setup(hass: HomeAssistant, fe2_url: str = FE2_URL) -> MockConfigEntry:
    await async_setup_component(hass, "http", {})
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Feuerwehr",
        data={CONF_WEBHOOK_ID: "test_webhook"},
        options={
            CONF_FE2_URL: fe2_url,
            CONF_FE2_SENDER: "Hausautomation",
            CONF_FE2_AUTHORIZATION: "ABC",
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_send_alarm(hass: HomeAssistant, aioclient_mock) -> None:
    """An alarm is sent in data format v2."""
    await _setup(hass)
    aioclient_mock.post(ALARM_URL, json={"status": "OK"})

    response = await hass.services.async_call(
        DOMAIN,
        "fe2_send_alarm",
        {
            "keyword": "BMA",
            "keyword_description": "Brandmeldeanlage",
            "message": "Rauchmelder Keller\n\nAusgelöst",
            "units": ["1234567"],
            "street": "Musterstraße",
            "house": "10",
            "city": "Musterhausen",
            "latitude": 50.12345,
            "longitude": 10.123456,
            "caller_name": "Home Assistant",
            "custom": {"remark": "Test"},
        },
        blocking=True,
        return_response=True,
    )

    result = response["results"][0]
    assert result["status"] == HTTPStatus.OK
    external_id = result["external_id"]
    assert external_id

    payload = aioclient_mock.mock_calls[0][2]
    assert payload["type"] == "ALARM"
    assert payload["sender"] == "Hausautomation"
    assert payload["authorization"] == "ABC"
    assert payload["timestamp"]
    assert payload["data"] == {
        "externalId": external_id,
        "keyword": "BMA",
        "keyword_description": "Brandmeldeanlage",
        "message": ["Rauchmelder Keller", "Ausgelöst"],
        "location": {
            "street": "Musterstraße",
            "house": "10",
            "city": "Musterhausen",
            "coordinate": [10.123456, 50.12345],
        },
        "caller": {"name": "Home Assistant"},
        "units": [{"address": "1234567"}],
        "custom": {"remark": "Test"},
    }


async def test_send_alarm_default_units(hass: HomeAssistant, aioclient_mock) -> None:
    """Without units an empty list is sent (FE2 default units)."""
    await _setup(hass)
    aioclient_mock.post(ALARM_URL, json={"status": "OK"})
    await hass.services.async_call(
        DOMAIN,
        "fe2_send_alarm",
        {"message": "Wassermelder", "external_id": "E-1"},
        blocking=True,
    )
    data = aioclient_mock.mock_calls[0][2]["data"]
    assert data == {"externalId": "E-1", "message": ["Wassermelder"], "units": []}


async def test_send_alarm_requires_content(hass: HomeAssistant) -> None:
    """Keyword or message is required."""
    await _setup(hass)
    with pytest.raises(vol.Invalid):
        await hass.services.async_call(
            DOMAIN, "fe2_send_alarm", {"units": ["1"]}, blocking=True
        )


async def test_close_alarm(hass: HomeAssistant, aioclient_mock) -> None:
    """An alarm is closed by its external ID."""
    await _setup(hass)
    aioclient_mock.post(ALARM_URL, json={"status": "OK"})
    await hass.services.async_call(
        DOMAIN, "fe2_close_alarm", {"external_id": "E-1"}, blocking=True
    )
    payload = aioclient_mock.mock_calls[0][2]
    assert payload["type"] == "CLOSE"
    assert payload["data"] == {"externalId": "E-1"}


async def test_send_status(hass: HomeAssistant, aioclient_mock) -> None:
    """A vehicle status is sent to the status endpoint."""
    await _setup(hass)
    aioclient_mock.post(STATUS_URL, json={"status": "OK"})
    await hass.services.async_call(
        DOMAIN,
        "fe2_send_status",
        {
            "status": "2",
            "event": "Wache an",
            "radio_name": "LF 40/1",
            "latitude": 48.342424,
            "longitude": 10.905622,
        },
        blocking=True,
    )
    payload = aioclient_mock.mock_calls[0][2]
    assert payload["type"] == "STATUS"
    assert payload["data"] == {
        "status": "2",
        "event": "Wache an",
        "radioName": "LF 40/1",
        "location": {"lat": 48.342424, "lng": 10.905622},
    }


@pytest.mark.parametrize(
    ("status", "body"),
    [
        (HTTPStatus.OK, {"status": "NOT_OK", "error": "Unbekannter Absender"}),
        (HTTPStatus.NOT_ACCEPTABLE, {"status": "NOT_OK", "error": "deaktiviert"}),
        (HTTPStatus.CONFLICT, None),
    ],
)
async def test_send_alarm_rejected(
    hass: HomeAssistant, aioclient_mock, status: HTTPStatus, body: dict | None
) -> None:
    """Rejections by FE2 raise an error."""
    await _setup(hass)
    aioclient_mock.post(ALARM_URL, status=status, json=body)
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            DOMAIN, "fe2_send_alarm", {"keyword": "F1"}, blocking=True
        )


async def test_not_configured(hass: HomeAssistant) -> None:
    """Without an FE2 URL the actions are rejected."""
    await _setup(hass, fe2_url="")
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN, "fe2_close_alarm", {"external_id": "E-1"}, blocking=True
        )


async def test_options_flow(hass: HomeAssistant) -> None:
    """The FE2 options are stored and cleaned."""
    entry = await _setup(hass, fe2_url="")
    assert entry.runtime_data.fe2 is None
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {"fe2_url": f" {FE2_URL}/ ", "fe2_sender": " ", "fe2_authorization": " x "},
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_FE2_URL] == f"{FE2_URL}/"
    assert entry.options[CONF_FE2_SENDER] == "Home Assistant"
    assert entry.options[CONF_FE2_AUTHORIZATION] == "x"
    assert entry.runtime_data.fe2 is not None
