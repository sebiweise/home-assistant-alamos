"""Binary sensor showing whether an alarm is active."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import AlamosConfigEntry
from .const import (
    ATTR_DATA,
    ATTR_FEEDBACK_DEADLINE,
    ATTR_KEYWORD,
    ATTR_SOURCE,
    ATTR_UNIT,
    ATTR_UNITS,
)
from .entity import AlamosEntity

ALARM_DESCRIPTION = BinarySensorEntityDescription(
    key="alarm",
    translation_key="alarm",
)


# Home Assistant requires this exact coroutine signature.
async def async_setup_entry(  # NOSONAR
    hass: HomeAssistant,  # NOSONAR
    entry: AlamosConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the binary sensor."""
    async_add_entities([AlamosAlarmBinarySensor(entry, ALARM_DESCRIPTION)])


class AlamosAlarmBinarySensor(AlamosEntity, BinarySensorEntity):
    """On while an alarm is active."""

    @property
    def is_on(self) -> bool:
        """Return True if an alarm is active."""
        return self.manager.state.active

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the data of the last alarm."""
        state = self.manager.state
        return {
            ATTR_KEYWORD: state.keyword,
            ATTR_UNIT: state.unit,
            ATTR_UNITS: state.units,
            ATTR_SOURCE: state.source,
            ATTR_DATA: state.data,
            ATTR_FEEDBACK_DEADLINE: (
                deadline.isoformat()
                if (deadline := self.manager.feedback_deadline)
                else None
            ),
        }
