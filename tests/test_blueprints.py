"""Tests for the example automation blueprints."""

import asyncio
from collections.abc import Callable
from datetime import timedelta
from http import HTTPStatus
from pathlib import Path
import shutil
from unittest.mock import patch

import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
    async_mock_service,
)

from custom_components.alamos.const import (
    CONF_API_KEY,
    CONF_RESET_MINUTES,
    CONF_TEST_KEYWORDS,
    CONF_WEBHOOK_ID,
    DEFAULT_API_URL,
    DOMAIN,
    FEEDBACK_PATH,
)
from homeassistant.components.automation.config import AUTOMATION_BLUEPRINT_SCHEMA
from homeassistant.components.blueprint.models import Blueprint
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv, template
from homeassistant.setup import async_setup_component
from homeassistant.util.yaml import load_yaml

BLUEPRINT_DIR = Path(__file__).parent.parent / "blueprints" / "automation" / "alamos"
BLUEPRINTS = sorted(BLUEPRINT_DIR.glob("*.yaml"))
WEBHOOK_ID = "blueprint_webhook"
FEEDBACK_URL = f"{DEFAULT_API_URL}{FEEDBACK_PATH}"
DEVICE_ID = "phone"


async def _wait_for(predicate: Callable[[], bool]) -> None:
    """Wait until predicate is true.

    hass.async_block_till_done() would wait for automations that are paused
    in wait_for_trigger, so poll the expected outcome instead. Counts event
    loop iterations rather than time, because the freezer fixture stops the
    loop clock.
    """
    for _ in range(5000):
        if predicate():
            return
        await asyncio.sleep(0)
    raise AssertionError("condition not met")


class FakeMobileAppNotify:
    """Stand-in for the mobile_app 'notify' device action.

    Validates and renders the action like mobile_app does, without loading the
    mobile_app integration and its dependencies.
    """

    def __init__(self) -> None:
        self.notifications: list[dict] = []

    async def validate(self, hass, config):
        config = dict(config)
        for key in ("title", "message"):
            if key in config:
                config[key] = cv.template(config[key])
        if "data" in config:
            config["data"] = cv.template_complex(config["data"])
        return config

    async def call(self, hass, config, variables, context):
        assert config["domain"] == "mobile_app"
        assert config["device_id"] == DEVICE_ID
        self.notifications.append(
            {
                key: template.render_complex(config[key], variables)
                for key in ("title", "message", "data")
                if key in config
            }
        )

    def patch(self):
        return (
            patch(
                "homeassistant.helpers.script.device_action.async_validate_action_config",
                side_effect=self.validate,
            ),
            patch(
                "homeassistant.helpers.script.device_action.async_call_action_from_config",
                side_effect=self.call,
            ),
        )


@pytest.mark.parametrize("path", BLUEPRINTS, ids=lambda path: path.name)
def test_blueprint_schema(path: Path) -> None:
    """Every blueprint is a valid automation blueprint."""
    blueprint = Blueprint(
        load_yaml(path),
        expected_domain="automation",
        schema=AUTOMATION_BLUEPRINT_SCHEMA,
    )
    assert blueprint.metadata["source_url"].endswith(
        f"blueprints/automation/alamos/{path.name}"
    )


async def _setup(hass: HomeAssistant) -> MockConfigEntry:
    """Set up Alamos and copy the blueprints into the config directory."""
    target = Path(hass.config.path("blueprints/automation/alamos"))
    target.mkdir(parents=True, exist_ok=True)
    for path in BLUEPRINTS:
        shutil.copy(path, target / path.name)

    await async_setup_component(hass, "http", {})
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Feuerwehr",
        data={CONF_WEBHOOK_ID: WEBHOOK_ID},
        options={
            CONF_API_KEY: "secret",
            CONF_RESET_MINUTES: 30,
            CONF_TEST_KEYWORDS: ["Probealarm"],
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def _setup_automation(hass: HomeAssistant, blueprint: str, inputs: dict) -> None:
    assert await async_setup_component(
        hass,
        "automation",
        {
            "automation": {
                "alias": blueprint,
                "use_blueprint": {
                    "path": f"alamos/{blueprint}.yaml",
                    "input": inputs,
                },
            }
        },
    )
    await hass.async_block_till_done()
    state = hass.states.get(f"automation.{blueprint}")
    assert state is not None
    assert state.state == "on"


async def _send_alarm(client, keyword: str = "B3 Wohnung") -> None:
    resp = await client.get(
        f"/api/webhook/{WEBHOOK_ID}", params={"keyword": keyword, "unit": "LZ1"}
    )
    assert resp.status == HTTPStatus.OK


async def test_actionable_notification(
    hass: HomeAssistant, hass_client_no_auth, aioclient_mock
) -> None:
    """Pressing the accept action sends feedback and updates the notification."""
    entry = await _setup(hass)
    aioclient_mock.get(FEEDBACK_URL, status=200)
    phone = FakeMobileAppNotify()
    validate_patch, call_patch = phone.patch()

    with validate_patch, call_patch:
        await _setup_automation(
            hass,
            "actionable_notification",
            {"alamos_entry": entry.entry_id, "notify_device": DEVICE_ID},
        )
        client = await hass_client_no_auth()

        # Test alarms are ignored by default
        await _send_alarm(client, "Probealarm Sirene")
        await hass.async_block_till_done()
        assert phone.notifications == []

        await _send_alarm(client)
        await _wait_for(lambda: len(phone.notifications) == 1)

        first = phone.notifications[0]
        assert first["title"] == "🚨 B3 Wohnung"
        assert first["message"].startswith("LZ1 – ")
        actions = first["data"]["actions"]
        assert [action["title"] for action in actions] == ["✅ Komme", "❌ Komme nicht"]
        assert first["data"]["push"]["sound"]["critical"] == 1
        assert first["data"]["channel"] == "alarm_stream"

        hass.bus.async_fire(
            "mobile_app_notification_action", {"action": actions[0]["action"]}
        )
        await _wait_for(lambda: len(phone.notifications) == 2)

    assert len(aioclient_mock.mock_calls) == 1
    query = aioclient_mock.mock_calls[0][1].query
    assert query["mode"] == "accept"
    assert query["suppressNotification"] == "true"

    result = phone.notifications[1]
    assert result["title"] == "✅ Zusage – B3 Wohnung"
    assert result["message"] == "Rückmeldung an Alamos übermittelt."
    assert result["data"]["tag"] == first["data"]["tag"]


async def test_actionable_notification_reject_no_alarm(
    hass: HomeAssistant, hass_client_no_auth, aioclient_mock
) -> None:
    """Rejecting reports when Alamos found no alarm to answer."""
    entry = await _setup(hass)
    aioclient_mock.get(FEEDBACK_URL, status=204)
    phone = FakeMobileAppNotify()
    validate_patch, call_patch = phone.patch()

    with validate_patch, call_patch:
        await _setup_automation(
            hass,
            "actionable_notification",
            {
                "alamos_entry": entry.entry_id,
                "notify_device": DEVICE_ID,
                "critical": False,
            },
        )
        client = await hass_client_no_auth()
        await _send_alarm(client)
        await _wait_for(lambda: len(phone.notifications) == 1)
        first = phone.notifications[0]
        assert first["data"]["push"]["interruption-level"] == "time-sensitive"

        hass.bus.async_fire(
            "mobile_app_notification_action",
            {"action": first["data"]["actions"][1]["action"]},
        )
        await _wait_for(lambda: len(phone.notifications) == 2)

    assert aioclient_mock.mock_calls[0][1].query["mode"] == "reject"
    assert phone.notifications[1]["title"] == "❌ Absage – B3 Wohnung"
    assert "keinen Alarm" in phone.notifications[1]["message"]


async def test_actionable_notification_timeout(
    hass: HomeAssistant, hass_client_no_auth, aioclient_mock, freezer
) -> None:
    """Without an answer the notification is marked as expired."""
    entry = await _setup(hass)
    phone = FakeMobileAppNotify()
    validate_patch, call_patch = phone.patch()

    with validate_patch, call_patch:
        await _setup_automation(
            hass,
            "actionable_notification",
            {"alamos_entry": entry.entry_id, "notify_device": DEVICE_ID},
        )
        client = await hass_client_no_auth()
        await _send_alarm(client)
        await _wait_for(lambda: len(phone.notifications) == 1)

        freezer.tick(timedelta(minutes=4))
        async_fire_time_changed(hass)
        await _wait_for(lambda: len(phone.notifications) == 2)

    assert aioclient_mock.mock_calls == []
    assert phone.notifications[1]["title"] == "⏱️ B3 Wohnung"


@pytest.mark.parametrize(
    ("persons", "expected_mode"),
    [(["person.max"], "accept"), ([], "reject")],
)
async def test_presence_feedback(
    hass: HomeAssistant,
    hass_client_no_auth,
    aioclient_mock,
    persons: list[str],
    expected_mode: str,
) -> None:
    """Feedback depends on whether the person is inside the zone."""
    entry = await _setup(hass)
    aioclient_mock.get(FEEDBACK_URL, status=200)
    hass.states.async_set("zone.wache", "1", {"persons": persons})

    await _setup_automation(
        hass,
        "presence_feedback",
        {
            "alamos_entry": entry.entry_id,
            "person": "person.max",
            "zone": "zone.wache",
            "mode_in_zone": "accept",
            "mode_outside_zone": "reject",
            "delay": 0,
        },
    )
    client = await hass_client_no_auth()
    await _send_alarm(client)
    await hass.async_block_till_done()

    assert len(aioclient_mock.mock_calls) == 1
    assert aioclient_mock.mock_calls[0][1].query["mode"] == expected_mode


async def test_presence_feedback_none(
    hass: HomeAssistant, hass_client_no_auth, aioclient_mock
) -> None:
    """'none' sends no feedback."""
    entry = await _setup(hass)
    hass.states.async_set("zone.home", "0", {"persons": []})

    await _setup_automation(
        hass,
        "presence_feedback",
        {"alamos_entry": entry.entry_id, "person": "person.max", "delay": 0},
    )
    client = await hass_client_no_auth()
    await _send_alarm(client)
    await hass.async_block_till_done()

    assert aioclient_mock.mock_calls == []


async def test_alarm_lights(hass: HomeAssistant, hass_client_no_auth) -> None:
    """Lights are switched on and restored when the alarm ends."""
    await _setup(hass)
    hass.states.async_set("sun.sun", "below_horizon")
    scene_create = async_mock_service(hass, "scene", "create")
    scene_on = async_mock_service(hass, "scene", "turn_on")
    light_on = async_mock_service(hass, "light", "turn_on")

    await _setup_automation(
        hass,
        "alarm_lights",
        {
            "alarm_sensor": "binary_sensor.feuerwehr_alarm",
            "lights": ["light.flur", "light.treppe"],
            "brightness": 80,
        },
    )
    client = await hass_client_no_auth()
    await _send_alarm(client)
    await _wait_for(lambda: len(light_on) == 1)

    assert scene_create[0].data["snapshot_entities"] == ["light.flur", "light.treppe"]
    assert light_on[0].data["entity_id"] == ["light.flur", "light.treppe"]
    assert light_on[0].data["brightness_pct"] == 80
    assert scene_on == []

    await client.get(f"/api/webhook/{WEBHOOK_ID}?event=clear")
    await _wait_for(lambda: len(scene_on) == 1)
    assert scene_on[0].data["entity_id"] == ["scene.alamos_light_snapshot"]


async def test_alarm_lights_daytime(hass: HomeAssistant, hass_client_no_auth) -> None:
    """With 'only when dark' nothing happens during the day."""
    await _setup(hass)
    hass.states.async_set("sun.sun", "above_horizon")
    light_on = async_mock_service(hass, "light", "turn_on")
    async_mock_service(hass, "scene", "create")

    await _setup_automation(
        hass,
        "alarm_lights",
        {
            "alarm_sensor": "binary_sensor.feuerwehr_alarm",
            "lights": ["light.flur"],
        },
    )
    client = await hass_client_no_auth()
    await _send_alarm(client)
    await hass.async_block_till_done()
    assert light_on == []
