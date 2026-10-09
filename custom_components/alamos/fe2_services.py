"""Services for the FE2 external interface ("Externe Schnittstelle")."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any
import uuid

import voluptuous as vol

from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
    callback,
)
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.util import dt as dt_util

from .const import (
    ATTR_CONFIG_ENTRY_ID,
    DOMAIN,
    SERVICE_FE2_CLOSE_ALARM,
    SERVICE_FE2_SEND_ALARM,
    SERVICE_FE2_SEND_STATUS,
)
from .fe2 import Fe2Client, Fe2Error, Fe2Result

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

ATTR_EXTERNAL_ID = "external_id"
ATTR_KEYWORD = "keyword"
ATTR_KEYWORD_DESCRIPTION = "keyword_description"
ATTR_MESSAGE = "message"
ATTR_STREET = "street"
ATTR_HOUSE = "house"
ATTR_POSTAL_CODE = "postal_code"
ATTR_CITY = "city"
ATTR_BUILDING = "building"
ATTR_LATITUDE = "latitude"
ATTR_LONGITUDE = "longitude"
ATTR_UNITS = "units"
ATTR_CALLER_NAME = "caller_name"
ATTR_CALLER_CONTACT = "caller_contact"
ATTR_CUSTOM = "custom"
ATTR_STATUS = "status"
ATTR_EVENT = "event"
ATTR_ADDRESS = "address"
ATTR_RADIO_NAME = "radio_name"

CALLER_FIELDS = {ATTR_CALLER_NAME: "name", ATTR_CALLER_CONTACT: "contact"}

# FE2 field name inside data.location for each service field.
LOCATION_FIELDS = {
    ATTR_STREET: "street",
    ATTR_HOUSE: "house",
    ATTR_POSTAL_CODE: "postalCode",
    ATTR_CITY: "city",
    ATTR_BUILDING: "building",
}

SEND_ALARM_SCHEMA = vol.All(
    vol.Schema(
        {
            vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string,
            vol.Optional(ATTR_EXTERNAL_ID): cv.string,
            vol.Optional(ATTR_KEYWORD): cv.string,
            vol.Optional(ATTR_KEYWORD_DESCRIPTION): cv.string,
            vol.Optional(ATTR_MESSAGE): cv.string,
            vol.Optional(ATTR_STREET): cv.string,
            vol.Optional(ATTR_HOUSE): cv.string,
            vol.Optional(ATTR_POSTAL_CODE): cv.string,
            vol.Optional(ATTR_CITY): cv.string,
            vol.Optional(ATTR_BUILDING): cv.string,
            vol.Inclusive(ATTR_LATITUDE, "coordinates"): cv.latitude,
            vol.Inclusive(ATTR_LONGITUDE, "coordinates"): cv.longitude,
            vol.Optional(ATTR_UNITS): vol.All(cv.ensure_list, [cv.string]),
            vol.Optional(ATTR_CALLER_NAME): cv.string,
            vol.Optional(ATTR_CALLER_CONTACT): cv.string,
            vol.Optional(ATTR_CUSTOM): vol.Schema({cv.string: cv.string}),
        }
    ),
    cv.has_at_least_one_key(ATTR_KEYWORD, ATTR_MESSAGE),
)
CLOSE_ALARM_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string,
        vol.Required(ATTR_EXTERNAL_ID): cv.string,
    }
)
SEND_STATUS_SCHEMA = vol.All(
    vol.Schema(
        {
            vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string,
            vol.Required(ATTR_STATUS): cv.string,
            vol.Optional(ATTR_EVENT): cv.string,
            vol.Optional(ATTR_ADDRESS): cv.string,
            vol.Optional(ATTR_RADIO_NAME): cv.string,
            vol.Inclusive(ATTR_LATITUDE, "coordinates"): cv.latitude,
            vol.Inclusive(ATTR_LONGITUDE, "coordinates"): cv.longitude,
        }
    ),
    cv.has_at_least_one_key(ATTR_ADDRESS, ATTR_RADIO_NAME),
)


def build_alarm_data(call_data: dict[str, Any], external_id: str) -> dict[str, Any]:
    """Map the service data to the FE2 ``data`` object (data format v2)."""
    data: dict[str, Any] = {"externalId": external_id}
    if keyword := call_data.get(ATTR_KEYWORD):
        data["keyword"] = keyword
    if description := call_data.get(ATTR_KEYWORD_DESCRIPTION):
        data["keyword_description"] = description
    if message := call_data.get(ATTR_MESSAGE):
        data["message"] = [line for line in message.splitlines() if line.strip()]

    location = {
        fe2_key: call_data[key]
        for key, fe2_key in LOCATION_FIELDS.items()
        if call_data.get(key)
    }
    if ATTR_LATITUDE in call_data:
        # FE2 expects [longitude, latitude] (x, y).
        location["coordinate"] = [call_data[ATTR_LONGITUDE], call_data[ATTR_LATITUDE]]
    if location:
        data["location"] = location

    caller = {
        fe2_key: call_data[key]
        for key, fe2_key in CALLER_FIELDS.items()
        if call_data.get(key)
    }
    if caller:
        data["caller"] = caller

    # An empty unit list alarms the default units of the FE2 input.
    data["units"] = [{"address": unit} for unit in call_data.get(ATTR_UNITS, [])]
    if custom := call_data.get(ATTR_CUSTOM):
        data["custom"] = custom
    return data


def build_status_data(call_data: dict[str, Any]) -> dict[str, Any]:
    """Map the service data to the FE2 status ``data`` object."""
    data: dict[str, Any] = {"status": call_data[ATTR_STATUS]}
    for key, fe2_key in (
        (ATTR_EVENT, "event"),
        (ATTR_ADDRESS, "address"),
        (ATTR_RADIO_NAME, "radioName"),
    ):
        if call_data.get(key):
            data[fe2_key] = call_data[key]
    if ATTR_LATITUDE in call_data:
        data["location"] = {
            "lat": call_data[ATTR_LATITUDE],
            "lng": call_data[ATTR_LONGITUDE],
        }
    return data


@callback
def async_register_fe2_services(
    hass: HomeAssistant,
    get_entries: Callable[[HomeAssistant, str | None], list[ConfigEntry]],
) -> None:
    """Register the FE2 services."""

    def _clients(call: ServiceCall) -> list[tuple[ConfigEntry, Fe2Client]]:
        entries = get_entries(hass, call.data.get(ATTR_CONFIG_ENTRY_ID))
        clients = [
            (entry, entry.runtime_data.fe2)
            for entry in entries
            if entry.runtime_data.fe2 is not None
        ]
        if not clients:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="fe2_not_configured"
            )
        return clients

    async def _send(
        call: ServiceCall,
        send: Callable[[Fe2Client], Any],
        extra: dict[str, Any] | None = None,
    ) -> ServiceResponse:
        results = []
        for entry, client in _clients(call):
            try:
                result: Fe2Result = await send(client)
            except Fe2Error as err:
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="fe2_error",
                    translation_placeholders={"name": entry.title, "error": str(err)},
                ) from err
            results.append(
                {"config_entry_id": entry.entry_id, "status": result.status}
                | (extra or {})
            )
        return {"results": results}

    async def _handle_send_alarm(call: ServiceCall) -> ServiceResponse:
        external_id = call.data.get(ATTR_EXTERNAL_ID) or uuid.uuid4().hex
        data = build_alarm_data(dict(call.data), external_id)
        now = dt_util.now()
        return await _send(
            call,
            lambda client: client.async_send_alarm(data, now),
            {ATTR_EXTERNAL_ID: external_id},
        )

    async def _handle_close_alarm(call: ServiceCall) -> ServiceResponse:
        external_id = call.data[ATTR_EXTERNAL_ID]
        now = dt_util.now()
        return await _send(
            call,
            lambda client: client.async_close_alarm(external_id, now),
            {ATTR_EXTERNAL_ID: external_id},
        )

    async def _handle_send_status(call: ServiceCall) -> ServiceResponse:
        data = build_status_data(dict(call.data))
        now = dt_util.now()
        return await _send(call, lambda client: client.async_send_status(data, now))

    for service, handler, schema in (
        (SERVICE_FE2_SEND_ALARM, _handle_send_alarm, SEND_ALARM_SCHEMA),
        (SERVICE_FE2_CLOSE_ALARM, _handle_close_alarm, CLOSE_ALARM_SCHEMA),
        (SERVICE_FE2_SEND_STATUS, _handle_send_status, SEND_STATUS_SCHEMA),
    ):
        hass.services.async_register(
            DOMAIN,
            service,
            handler,
            schema=schema,
            supports_response=SupportsResponse.OPTIONAL,
        )
