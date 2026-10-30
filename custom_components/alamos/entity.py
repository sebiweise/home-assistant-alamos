"""Base entity for the Alamos integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity import Entity, EntityDescription

from . import entry_webhook_count
from .alarm import AlamosAlarmManager
from .const import (
    ATTR_DATA,
    CONF_RECORD_RAW_DATA,
    DEFAULT_RECORD_RAW_DATA,
    DOMAIN,
    MAX_WEBHOOKS,
)


def record_raw_data(entry: ConfigEntry) -> bool:
    """Return True if the raw webhook data is stored in the history."""
    return bool(entry.options.get(CONF_RECORD_RAW_DATA, DEFAULT_RECORD_RAW_DATA))


class UnrecordedDataMixin:
    """Keep the raw webhook data out of the recorder.

    Put it before the entity class. The attribute stays available in the
    state, e.g. for templates; it is just not stored in the history.
    """

    _unrecorded_attributes = frozenset({ATTR_DATA})


def webhook_entity_numbers(entry: ConfigEntry) -> range:
    """Return the webhooks with their own entities, none for a single webhook."""
    count = entry_webhook_count(entry)
    return range(1, count + 1) if count > 1 else range(0)


@callback
def async_remove_webhook_entities(
    hass: HomeAssistant, entry: ConfigEntry, domain: str, key: str, keep: range
) -> None:
    """Remove the entities of the webhooks which do not have their own anymore."""
    registry = er.async_get(hass)
    for number in range(1, MAX_WEBHOOKS + 1):
        if number in keep:
            continue
        if entity_id := registry.async_get_entity_id(
            domain, DOMAIN, f"{entry.entry_id}_{key}_{number}"
        ):
            registry.async_remove(entity_id)


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
