"""Sensors for the Alamos integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    RestoreSensor,
    SensorDeviceClass,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType

from . import AlamosConfigEntry
from .alarm import AlarmState
from .const import ATTR_DATA, ATTR_UNIT, ATTR_UNITS
from .entity import AlamosEntity

# Home Assistant does not accept states longer than 255 characters.
MAX_STATE_LENGTH = 255

FEEDBACK_RESULTS = [
    "success",
    "no_alarm",
    "invalid_api_key",
    "no_subscription",
    "error",
]


@dataclass(frozen=True, kw_only=True)
class AlamosSensorEntityDescription(SensorEntityDescription):
    """Describes an Alamos sensor."""

    value_fn: Callable[[AlarmState], StateType | datetime]
    attrs_fn: Callable[[AlarmState], dict[str, Any]] | None = None
    requires_api: bool = False


SENSORS: tuple[AlamosSensorEntityDescription, ...] = (
    AlamosSensorEntityDescription(
        key="keyword",
        translation_key="keyword",
        value_fn=lambda state: state.keyword,
        attrs_fn=lambda state: {
            ATTR_UNIT: state.unit,
            ATTR_UNITS: state.units,
            ATTR_DATA: state.data,
        },
    ),
    AlamosSensorEntityDescription(
        key="unit",
        translation_key="unit",
        value_fn=lambda state: _units_text(state),
        attrs_fn=lambda state: {ATTR_UNIT: state.unit, ATTR_UNITS: state.units},
    ),
    AlamosSensorEntityDescription(
        key="last_alarm",
        translation_key="last_alarm",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda state: state.last_alarm,
    ),
    AlamosSensorEntityDescription(
        key="alarm_count",
        translation_key="alarm_count",
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda state: state.alarm_count,
    ),
    AlamosSensorEntityDescription(
        key="last_webhook",
        translation_key="last_webhook",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda state: (
            state.last_webhook.timestamp if state.last_webhook else None
        ),
        attrs_fn=lambda state: (
            {
                # The state is shown in seconds; the exact time makes every
                # call a new entry in the history, even within one second.
                "received": state.last_webhook.timestamp.isoformat(),
                "method": state.last_webhook.method,
                "result": state.last_webhook.result,
                ATTR_DATA: state.last_webhook.data,
            }
            if state.last_webhook
            else {}
        ),
    ),
    AlamosSensorEntityDescription(
        key="last_feedback",
        translation_key="last_feedback",
        device_class=SensorDeviceClass.ENUM,
        options=FEEDBACK_RESULTS,
        requires_api=True,
        value_fn=lambda state: state.feedback.result if state.feedback else None,
        attrs_fn=lambda state: (
            {
                "mode": state.feedback.mode,
                "timestamp": state.feedback.timestamp.isoformat(),
            }
            if state.feedback
            else {}
        ),
    ),
)


def _units_text(state: AlarmState) -> str | None:
    """Return all alarmed units, the favorite / first one leading."""
    if not state.units:
        return state.unit
    text = ", ".join(state.units)
    if len(text) > MAX_STATE_LENGTH:
        text = text[: MAX_STATE_LENGTH - 1] + "…"
    return text


# Home Assistant requires this exact coroutine signature.
async def async_setup_entry(  # NOSONAR
    hass: HomeAssistant,  # NOSONAR
    entry: AlamosConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the sensors."""
    has_api = entry.runtime_data.client is not None
    async_add_entities(
        AlamosSensor(entry, description)
        for description in SENSORS
        if has_api or not description.requires_api
    )


class AlamosSensor(AlamosEntity, RestoreSensor):
    """Sensor exposing a value of the last alarm."""

    entity_description: AlamosSensorEntityDescription

    async def async_added_to_hass(self) -> None:
        """Restore the last known value."""
        await super().async_added_to_hass()
        if (last := await self.async_get_last_sensor_data()) is None:
            return
        value = last.native_value
        if value is None:
            return
        key = self.entity_description.key
        if key == "alarm_count":
            self.manager.async_restore(alarm_count=int(value))
        elif key == "last_alarm" and isinstance(value, datetime):
            self.manager.async_restore(last_alarm=value)

    @property
    def native_value(self) -> StateType | datetime:
        """Return the sensor value."""
        return self.entity_description.value_fn(self.manager.state)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return extra attributes."""
        if self.entity_description.attrs_fn is None:
            return None
        return self.entity_description.attrs_fn(self.manager.state)
