"""The Alamos integration (aPager PRO / AMweb)."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.components import webhook
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import Platform
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
    callback,
)
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

from .alarm import AlamosAlarmManager, AlamosRuntimeData
from .api import (
    AlamosApiClient,
    AlamosApiError,
    AlamosAuthError,
    AlamosSubscriptionError,
)
from .const import (
    ATTR_CONFIG_ENTRY_ID,
    ATTR_MODE,
    ATTR_SUPPRESS_NOTIFICATION,
    CONF_API_KEY,
    CONF_API_URL,
    CONF_CLEAR_WEBHOOK_ID,
    CONF_RESET_MINUTES,
    CONF_SUPPRESS_NOTIFICATION,
    CONF_WEBHOOK_ID,
    DEFAULT_API_URL,
    DEFAULT_RESET_MINUTES,
    DOMAIN,
    EVENT_ALARM,
    EVENT_ALARM_CLEARED,
    EVENT_TYPE_CLEARED,
    FEEDBACK_MODES,
    SERVICE_RESET_ALARM,
    SERVICE_SEND_FEEDBACK,
)
from .receiver import async_create_clear_webhook_handler, async_create_webhook_handler

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.EVENT,
    Platform.SENSOR,
]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

type AlamosConfigEntry = ConfigEntry[AlamosRuntimeData]

SEND_FEEDBACK_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string,
        vol.Required(ATTR_MODE): vol.In(FEEDBACK_MODES),
        vol.Optional(ATTR_SUPPRESS_NOTIFICATION): cv.boolean,
    }
)
RESET_ALARM_SCHEMA = vol.Schema({vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string})


# Home Assistant requires this exact coroutine signature.
async def async_setup(  # NOSONAR
    hass: HomeAssistant,
    config: ConfigType,  # NOSONAR
) -> bool:
    """Register the integration services."""
    _async_register_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: AlamosConfigEntry) -> bool:
    """Set up Alamos from a config entry."""
    options = entry.options
    manager = AlamosAlarmManager(
        hass, int(options.get(CONF_RESET_MINUTES, DEFAULT_RESET_MINUTES))
    )

    client: AlamosApiClient | None = None
    if api_key := options.get(CONF_API_KEY):
        client = AlamosApiClient(
            async_get_clientsession(hass),
            api_key,
            options.get(CONF_API_URL) or DEFAULT_API_URL,
        )

    entry.runtime_data = AlamosRuntimeData(manager=manager, client=client)

    @callback
    def _fire_bus_event(event_type: str, data: dict[str, Any]) -> None:
        hass.bus.async_fire(
            EVENT_ALARM_CLEARED if event_type == EVENT_TYPE_CLEARED else EVENT_ALARM,
            {ATTR_CONFIG_ENTRY_ID: entry.entry_id, "name": entry.title, **data},
        )

    entry.async_on_unload(manager.async_add_event_listener(_fire_bus_event))
    entry.async_on_unload(manager.async_shutdown)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    _async_register_webhook(
        hass,
        entry,
        f"Alamos {entry.title}",
        entry.data[CONF_WEBHOOK_ID],
        async_create_webhook_handler(entry),
    )
    _async_register_webhook(
        hass,
        entry,
        f"Alamos {entry.title} (recall)",
        entry.data[CONF_CLEAR_WEBHOOK_ID],
        async_create_clear_webhook_handler(entry),
    )
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    return True


@callback
def _async_register_webhook(
    hass: HomeAssistant,
    entry: AlamosConfigEntry,
    name: str,
    webhook_id: str,
    handler: Any,
) -> None:
    webhook.async_register(
        hass,
        DOMAIN,
        name,
        webhook_id,
        handler,
        local_only=False,
        allowed_methods=["GET", "POST", "PUT"],
    )
    entry.async_on_unload(lambda: webhook.async_unregister(hass, webhook_id))


async def async_migrate_entry(hass: HomeAssistant, entry: AlamosConfigEntry) -> bool:
    """Migrate old config entries."""
    if entry.version > 1:
        return False

    if entry.minor_version < 2:
        # 1.2 adds the separate recall (Rückalarm) webhook.
        hass.config_entries.async_update_entry(
            entry,
            data={**entry.data, CONF_CLEAR_WEBHOOK_ID: webhook.async_generate_id()},
            minor_version=2,
        )
        _LOGGER.debug("Migrated Alamos entry %s to version 1.2", entry.entry_id)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: AlamosConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_update_listener(hass: HomeAssistant, entry: AlamosConfigEntry) -> None:
    """Reload the entry when the options change."""
    await hass.config_entries.async_reload(entry.entry_id)


@callback
def _async_get_entries(
    hass: HomeAssistant, entry_id: str | None
) -> list[AlamosConfigEntry]:
    """Return the loaded entries targeted by a service call."""
    entries = [
        entry
        for entry in hass.config_entries.async_entries(DOMAIN)
        if entry.state is ConfigEntryState.LOADED
        and (entry_id is None or entry.entry_id == entry_id)
    ]
    if not entries:
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="entry_not_found"
        )
    return entries


async def async_send_feedback(
    entry: AlamosConfigEntry,
    mode: str,
    suppress_notification: bool | None = None,
) -> dict[str, Any]:
    """Send feedback for one entry and update its state."""
    runtime = entry.runtime_data
    if runtime.client is None:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="no_api_key",
            translation_placeholders={"name": entry.title},
        )
    if suppress_notification is None:
        suppress_notification = entry.options.get(CONF_SUPPRESS_NOTIFICATION, False)

    try:
        result = await runtime.client.async_send_feedback(mode, suppress_notification)
    except AlamosAuthError as err:
        runtime.manager.async_feedback(mode, "invalid_api_key")
        raise HomeAssistantError(
            translation_domain=DOMAIN, translation_key="invalid_api_key"
        ) from err
    except AlamosSubscriptionError as err:
        runtime.manager.async_feedback(mode, "no_subscription")
        raise HomeAssistantError(
            translation_domain=DOMAIN, translation_key="no_subscription"
        ) from err
    except AlamosApiError as err:
        runtime.manager.async_feedback(mode, "error")
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="api_error",
            translation_placeholders={"error": str(err)},
        ) from err

    runtime.manager.async_feedback(mode, result.result)
    return {
        "config_entry_id": entry.entry_id,
        "mode": mode,
        "status": result.status,
        "result": result.result,
    }


@callback
def _async_register_services(hass: HomeAssistant) -> None:
    async def _handle_send_feedback(call: ServiceCall) -> ServiceResponse:
        entries = _async_get_entries(hass, call.data.get(ATTR_CONFIG_ENTRY_ID))
        entries = [entry for entry in entries if entry.runtime_data.client is not None]
        if not entries:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="no_api_key",
                translation_placeholders={"name": DOMAIN},
            )
        results = [
            await async_send_feedback(
                entry,
                call.data[ATTR_MODE],
                call.data.get(ATTR_SUPPRESS_NOTIFICATION),
            )
            for entry in entries
        ]
        return {"results": results}

    @callback
    def _handle_reset_alarm(call: ServiceCall) -> None:
        for entry in _async_get_entries(hass, call.data.get(ATTR_CONFIG_ENTRY_ID)):
            entry.runtime_data.manager.async_clear(EVENT_TYPE_CLEARED)

    hass.services.async_register(
        DOMAIN,
        SERVICE_SEND_FEEDBACK,
        _handle_send_feedback,
        schema=SEND_FEEDBACK_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_RESET_ALARM,
        _handle_reset_alarm,
        schema=RESET_ALARM_SCHEMA,
    )
