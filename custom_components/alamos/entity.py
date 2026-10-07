"""Base entity for the Alamos integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity import Entity, EntityDescription

from .alarm import AlamosAlarmManager
from .const import DOMAIN


class AlamosEntity(Entity):
    """Common base for Alamos entities."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, entry: ConfigEntry, description: EntityDescription) -> None:
        """Initialize the entity."""
        self.entity_description = description
        self.manager: AlamosAlarmManager = entry.runtime_data.manager
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Alamos GmbH",
            model="aPager PRO / AMweb",
            entry_type=DeviceEntryType.SERVICE,
        )

    async def async_added_to_hass(self) -> None:
        """Subscribe to state updates."""
        await super().async_added_to_hass()
        self.async_on_remove(self.manager.async_add_listener(self.async_write_ha_state))
