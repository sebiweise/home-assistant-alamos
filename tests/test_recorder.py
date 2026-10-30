"""Tests for the raw webhook data in the recorder history."""

from datetime import timedelta

import pytest
from pytest_homeassistant_custom_component.components.recorder.common import (
    async_wait_recording_done,
)

from custom_components.alamos import entry_webhook_ids
from custom_components.alamos.const import CONF_RECORD_RAW_DATA, CONF_WEBHOOK_COUNT
from homeassistant.components.recorder import Recorder
from homeassistant.components.recorder.history import get_significant_states
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .test_init import _setup

ENTITY_IDS = [
    "binary_sensor.feuerwehr_alarm",
    "sensor.feuerwehr_keyword",
    "sensor.feuerwehr_last_webhook",
    "event.feuerwehr_alarm_event",
    "event.feuerwehr_alarm_event_webhook_1",
]
PAYLOAD = {"keyword": "B3", "unit": "LZ1", "address": "Musterstraße 1"}


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(
    recorder_mock: Recorder, enable_custom_integrations: None
) -> None:
    """Set up the recorder before Home Assistant, as it requires."""


async def _recorded_attributes(
    hass: HomeAssistant, hass_client_no_auth, **options
) -> dict[str, list[dict]]:
    """Send an alarm and return the recorded attributes per entity."""
    start = dt_util.utcnow() - timedelta(minutes=1)
    entry = await _setup(hass, **{CONF_WEBHOOK_COUNT: 2, **options})
    client = await hass_client_no_auth()
    await client.post(f"/api/webhook/{entry_webhook_ids(entry)[0]}", json=PAYLOAD)
    await hass.async_block_till_done()
    await async_wait_recording_done(hass)

    # The current state always has the raw data.
    for entity_id in ENTITY_IDS:
        assert hass.states.get(entity_id).attributes["data"] == PAYLOAD

    history = await hass.async_add_executor_job(
        get_significant_states, hass, start, None, ENTITY_IDS, None, True, False
    )
    return {
        entity_id: [dict(state.attributes) for state in history[entity_id]]
        for entity_id in ENTITY_IDS
    }


async def test_raw_data_not_recorded(hass: HomeAssistant, hass_client_no_auth) -> None:
    """By default, the raw data stays out of the history."""
    recorded = await _recorded_attributes(hass, hass_client_no_auth)
    for entity_id, states in recorded.items():
        assert states, entity_id
        assert all("data" not in attributes for attributes in states), entity_id
    assert recorded["binary_sensor.feuerwehr_alarm"][-1]["keyword"] == "B3"


async def test_raw_data_recorded_with_option(
    hass: HomeAssistant, hass_client_no_auth
) -> None:
    """With the option, the raw data is stored in the history as before."""
    recorded = await _recorded_attributes(
        hass, hass_client_no_auth, **{CONF_RECORD_RAW_DATA: True}
    )
    for entity_id, states in recorded.items():
        assert states[-1]["data"] == PAYLOAD, entity_id
