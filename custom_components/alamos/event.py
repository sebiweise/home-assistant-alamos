"""Event entity for incoming Alamos alarms."""

from __future__ import annotations

from typing import Any

from homeassistant.components.event import EventEntity, EventEntityDescription
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import AlamosConfigEntry
from .const import EVENT_TYPE_ALARM, EVENT_TYPE_CLEARED
from .entity import AlamosEntity

EVENT_DESCRIPTION = EventEntityDescription(
    key="webhook",
    translation_key="webhook",
    event_types=[EVENT_TYPE_ALARM, EVENT_TYPE_CLEARED],
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AlamosConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the event entity."""
    async_add_entities([AlamosEvent(entry, EVENT_DESCRIPTION)])


class AlamosEvent(AlamosEntity, EventEntity):
    """Fires for every alarm received through the webhook."""

    async def async_added_to_hass(self) -> None:
        """Subscribe to alarm events."""
        self.async_on_remove(self.manager.async_add_event_listener(self._handle_event))

    @callback
    def _handle_event(self, event_type: str, data: dict[str, Any]) -> None:
        self._trigger_event(event_type, data)
        self.async_write_ha_state()
