"""The Alamos integration (aPager PRO / AMweb)."""

from __future__ import annotations

from functools import partial
import logging
from typing import Any

import voluptuous as vol
from yarl import URL

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
from homeassistant.helpers import config_validation as cv, issue_registry as ir
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
    ATTR_WEBHOOK,
    CONF_ADDITIONAL_WEBHOOK_IDS,
    CONF_API_KEY,
    CONF_API_URL,
    CONF_FAVORITE_UNIT,
    CONF_RESET_MINUTES,
    CONF_SUPPRESS_NOTIFICATION,
    CONF_WEBHOOK_COUNT,
    CONF_WEBHOOK_ID,
    DATA_ALARM_SNAPSHOTS,
    DEFAULT_API_URL,
    DEFAULT_RESET_MINUTES,
    DEFAULT_WEBHOOK_COUNT,
    DOMAIN,
    EVENT_ALARM,
    EVENT_ALARM_CLEARED,
    EVENT_TYPE_CLEARED,
    FEEDBACK_MODES,
    FEEDBACK_RESULT_ERROR,
    FEEDBACK_RESULT_INVALID_API_KEY,
    FEEDBACK_RESULT_NO_SUBSCRIPTION,
    MAX_WEBHOOKS,
    SERVICE_RESET_ALARM,
    SERVICE_RESET_ALARM_COUNT,
    SERVICE_SEND_FEEDBACK,
)
from .receiver import async_create_webhook_handler

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
RESET_ALARM_COUNT_SCHEMA = RESET_ALARM_SCHEMA.extend(
    {
        vol.Optional(ATTR_WEBHOOK): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=MAX_WEBHOOKS)
        )
    }
)


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
        hass,
        int(options.get(CONF_RESET_MINUTES, DEFAULT_RESET_MINUTES)),
        options.get(CONF_FAVORITE_UNIT) or None,
    )
    # A running alarm survives the reload after an options change.
    snapshot = hass.data.get(DATA_ALARM_SNAPSHOTS, {}).pop(entry.entry_id, None)
    if snapshot is not None:
        manager.async_load_snapshot(snapshot)

    client: AlamosApiClient | None = None
    api_url = options.get(CONF_API_URL) or DEFAULT_API_URL
    if api_key := options.get(CONF_API_KEY):
        client = AlamosApiClient(async_get_clientsession(hass), api_key, api_url)
    _async_check_api_url(hass, entry, api_url if client else None)

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
    # All webhooks stay registered, so a URL still set in the app never loses
    # an alarm when the number of webhooks is reduced.
    for number, webhook_id in enumerate(entry_webhook_ids(entry), start=1):
        webhook.async_register(
            hass,
            DOMAIN,
            f"Alamos {entry.title} ({number})",
            webhook_id,
            async_create_webhook_handler(entry, number),
            local_only=False,
            allowed_methods=["GET", "POST", "PUT"],
        )
        entry.async_on_unload(partial(webhook.async_unregister, hass, webhook_id))
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    if snapshot is not None:
        manager.async_resume()

    return True


# Home Assistant requires this exact coroutine signature.
async def async_migrate_entry(  # NOSONAR
    hass: HomeAssistant, entry: AlamosConfigEntry
) -> bool:
    """Migrate an old config entry."""
    if entry.version > 1:
        return False
    if entry.minor_version < 2:
        hass.config_entries.async_update_entry(
            entry,
            data={
                **entry.data,
                CONF_ADDITIONAL_WEBHOOK_IDS: [
                    webhook.async_generate_id() for _ in range(MAX_WEBHOOKS - 1)
                ],
            },
            minor_version=2,
        )
    return True


def entry_webhook_ids(entry: ConfigEntry) -> list[str]:
    """Return the IDs of all webhooks, webhook 1 first."""
    return [entry.data[CONF_WEBHOOK_ID], *entry.data[CONF_ADDITIONAL_WEBHOOK_IDS]]


def entry_webhook_count(entry: ConfigEntry) -> int:
    """Return the number of webhooks with their own alarm count."""
    return int(entry.options.get(CONF_WEBHOOK_COUNT, DEFAULT_WEBHOOK_COUNT))


async def async_unload_entry(hass: HomeAssistant, entry: AlamosConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


# Home Assistant requires this exact coroutine signature.
async def async_remove_entry(  # NOSONAR
    hass: HomeAssistant, entry: AlamosConfigEntry
) -> None:
    """Remove the repair issue of a deleted entry."""
    ir.async_delete_issue(hass, DOMAIN, _insecure_api_url_issue_id(entry))


def _insecure_api_url_issue_id(entry: ConfigEntry) -> str:
    return f"insecure_api_url_{entry.entry_id}"


@callback
def _async_check_api_url(
    hass: HomeAssistant, entry: AlamosConfigEntry, api_url: str | None
) -> None:
    """Warn if the API key would be sent unencrypted.

    Plain HTTP stays allowed, e.g. for a server in the local network, but
    the API key is part of every feedback request.
    """
    issue_id = _insecure_api_url_issue_id(entry)
    if api_url is None or URL(api_url).scheme != "http":
        ir.async_delete_issue(hass, DOMAIN, issue_id)
        return
    _LOGGER.warning(
        "The Alamos API URL of %s uses http://, the API key is sent unencrypted",
        entry.title,
    )
    ir.async_create_issue(
        hass,
        DOMAIN,
        issue_id,
        is_fixable=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key="insecure_api_url",
        translation_placeholders={"name": entry.title, "url": api_url},
    )


async def _async_update_listener(hass: HomeAssistant, entry: AlamosConfigEntry) -> None:
    """Reload the entry when the options change, keeping a running alarm."""
    if entry.state is ConfigEntryState.LOADED:
        hass.data.setdefault(DATA_ALARM_SNAPSHOTS, {})[entry.entry_id] = (
            entry.runtime_data.manager.async_snapshot()
        )
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
        runtime.manager.async_feedback(mode, FEEDBACK_RESULT_INVALID_API_KEY)
        raise HomeAssistantError(
            translation_domain=DOMAIN, translation_key="invalid_api_key"
        ) from err
    except AlamosSubscriptionError as err:
        runtime.manager.async_feedback(mode, FEEDBACK_RESULT_NO_SUBSCRIPTION)
        raise HomeAssistantError(
            translation_domain=DOMAIN, translation_key="no_subscription"
        ) from err
    except AlamosApiError as err:
        runtime.manager.async_feedback(mode, FEEDBACK_RESULT_ERROR)
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


def _failed_feedback(
    entry: AlamosConfigEntry, mode: str, err: HomeAssistantError
) -> dict[str, Any]:
    """Return the service response for an entry whose feedback failed."""
    feedback = entry.runtime_data.manager.state.feedback
    return {
        "config_entry_id": entry.entry_id,
        "mode": mode,
        "status": None,
        "result": feedback.result if feedback else "error",
        "error": str(err),
    }


@callback
def _async_register_services(hass: HomeAssistant) -> None:
    async def _handle_send_feedback(call: ServiceCall) -> ServiceResponse:
        entries = _async_get_entries(hass, call.data.get(ATTR_CONFIG_ENTRY_ID))
        with_api = [entry for entry in entries if entry.runtime_data.client is not None]
        if not with_api:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="no_api_key",
                translation_placeholders={
                    "name": ", ".join(entry.title for entry in entries)
                },
            )
        mode = call.data[ATTR_MODE]
        results: list[dict[str, Any]] = []
        errors: list[HomeAssistantError] = []
        # A failing entry does not keep the others from answering; the
        # service only fails if no entry could answer.
        for entry in with_api:
            try:
                result = await async_send_feedback(
                    entry, mode, call.data.get(ATTR_SUPPRESS_NOTIFICATION)
                )
            except HomeAssistantError as err:
                _LOGGER.warning("Feedback for %s failed: %s", entry.title, err)
                errors.append(err)
                results.append(_failed_feedback(entry, mode, err))
            else:
                results.append(result)
        if len(errors) == len(with_api):
            raise errors[0]
        return {"results": results}

    @callback
    def _handle_reset_alarm(call: ServiceCall) -> None:
        for entry in _async_get_entries(hass, call.data.get(ATTR_CONFIG_ENTRY_ID)):
            entry.runtime_data.manager.async_clear(EVENT_TYPE_CLEARED)

    @callback
    def _handle_reset_alarm_count(call: ServiceCall) -> None:
        for entry in _async_get_entries(hass, call.data.get(ATTR_CONFIG_ENTRY_ID)):
            entry.runtime_data.manager.async_reset_count(call.data.get(ATTR_WEBHOOK))

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
    hass.services.async_register(
        DOMAIN,
        SERVICE_RESET_ALARM_COUNT,
        _handle_reset_alarm_count,
        schema=RESET_ALARM_COUNT_SCHEMA,
    )
