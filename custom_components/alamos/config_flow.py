"""Config flow for the Alamos integration."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components import webhook
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import selector

from . import entry_webhook_ids
from .const import (
    CONF_ADDITIONAL_WEBHOOK_IDS,
    CONF_API_KEY,
    CONF_API_URL,
    CONF_AVAILABILITY_CALENDARS,
    CONF_AVAILABILITY_KEYWORDS,
    CONF_CALENDAR_WEBHOOK_ID,
    CONF_FAVORITE_UNIT,
    CONF_KEYWORD_PARAM,
    CONF_RECORD_RAW_DATA,
    CONF_RESET_MINUTES,
    CONF_SUPPRESS_NOTIFICATION,
    CONF_TEST_KEYWORDS,
    CONF_UNIT_FILTER,
    CONF_UNIT_PARAM,
    CONF_WEBHOOK_COUNT,
    CONF_WEBHOOK_ID,
    DEFAULT_API_URL,
    DEFAULT_KEYWORD_PARAM,
    DEFAULT_RECORD_RAW_DATA,
    DEFAULT_RESET_MINUTES,
    DEFAULT_UNIT_PARAM,
    DEFAULT_WEBHOOK_COUNT,
    DOMAIN,
    MAX_WEBHOOKS,
    WEBHOOK_EVENT_PARAM,
)

PASSWORD_SELECTOR = selector.TextSelector(
    selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
)
URL_SELECTOR = selector.TextSelector(
    selector.TextSelectorConfig(type=selector.TextSelectorType.URL)
)
LIST_SELECTOR = selector.TextSelector(selector.TextSelectorConfig(multiple=True))
MINUTES_SELECTOR = selector.NumberSelector(
    selector.NumberSelectorConfig(
        min=0,
        max=1440,
        step=1,
        unit_of_measurement="min",
        mode=selector.NumberSelectorMode.BOX,
    )
)
WEBHOOK_COUNT_SELECTOR = selector.NumberSelector(
    selector.NumberSelectorConfig(
        min=1, max=MAX_WEBHOOKS, step=1, mode=selector.NumberSelectorMode.BOX
    )
)


CALENDAR_SELECTOR = selector.EntitySelector(
    selector.EntitySelectorConfig(domain="calendar", multiple=True)
)


def _webhook_url(hass: HomeAssistant, webhook_id: str) -> str:
    """Return the URL of a webhook, or its path without a configured URL."""
    try:
        return webhook.async_generate_url(hass, webhook_id)
    except HomeAssistantError:  # no external/internal URL configured yet
        return webhook.async_generate_path(webhook_id)


def _webhook_placeholders(
    hass: HomeAssistant, webhook_ids: list[str]
) -> dict[str, str]:
    """Return the webhook URLs shown in the config and options flow."""
    url = _webhook_url(hass, webhook_ids[0])
    return {
        "webhook_url": url,
        "webhook_clear_url": f"{url}?{WEBHOOK_EVENT_PARAM}=clear",
        "webhook_recall_url": f"{url}?{WEBHOOK_EVENT_PARAM}=recall",
        "additional_webhooks": "".join(
            f"\n\nWebhook {number}:\n`{_webhook_url(hass, webhook_id)}`"
            for number, webhook_id in enumerate(webhook_ids[1:], start=2)
        ),
    }


def _options_schema(options: dict[str, Any]) -> vol.Schema:
    """Return the options schema with the current values as defaults."""
    return vol.Schema(
        {
            vol.Optional(
                CONF_API_KEY,
                description={"suggested_value": options.get(CONF_API_KEY)},
            ): PASSWORD_SELECTOR,
            vol.Optional(
                CONF_SUPPRESS_NOTIFICATION,
                default=options.get(CONF_SUPPRESS_NOTIFICATION, False),
            ): selector.BooleanSelector(),
            vol.Optional(
                CONF_RESET_MINUTES,
                default=options.get(CONF_RESET_MINUTES, DEFAULT_RESET_MINUTES),
            ): MINUTES_SELECTOR,
            vol.Optional(
                CONF_WEBHOOK_COUNT,
                default=options.get(CONF_WEBHOOK_COUNT, DEFAULT_WEBHOOK_COUNT),
            ): WEBHOOK_COUNT_SELECTOR,
            vol.Optional(
                CONF_UNIT_FILTER,
                default=options.get(CONF_UNIT_FILTER, []),
            ): LIST_SELECTOR,
            vol.Optional(
                CONF_FAVORITE_UNIT,
                description={"suggested_value": options.get(CONF_FAVORITE_UNIT)},
            ): selector.TextSelector(),
            vol.Optional(
                CONF_TEST_KEYWORDS,
                default=options.get(CONF_TEST_KEYWORDS, []),
            ): LIST_SELECTOR,
            vol.Optional(
                CONF_AVAILABILITY_CALENDARS,
                default=options.get(CONF_AVAILABILITY_CALENDARS, []),
            ): CALENDAR_SELECTOR,
            vol.Optional(
                CONF_AVAILABILITY_KEYWORDS,
                default=options.get(CONF_AVAILABILITY_KEYWORDS, []),
            ): LIST_SELECTOR,
            vol.Optional(
                CONF_KEYWORD_PARAM,
                default=options.get(CONF_KEYWORD_PARAM, DEFAULT_KEYWORD_PARAM),
            ): selector.TextSelector(),
            vol.Optional(
                CONF_UNIT_PARAM,
                default=options.get(CONF_UNIT_PARAM, DEFAULT_UNIT_PARAM),
            ): selector.TextSelector(),
            vol.Optional(
                CONF_RECORD_RAW_DATA,
                default=options.get(CONF_RECORD_RAW_DATA, DEFAULT_RECORD_RAW_DATA),
            ): selector.BooleanSelector(),
            vol.Optional(
                CONF_API_URL,
                default=options.get(CONF_API_URL, DEFAULT_API_URL),
            ): URL_SELECTOR,
        }
    )


def _clean_options(user_input: dict[str, Any]) -> dict[str, Any]:
    """Strip text options and drop empty list entries."""
    options = dict(user_input)
    options[CONF_API_KEY] = (options.get(CONF_API_KEY) or "").strip()
    options[CONF_RESET_MINUTES] = int(
        options.get(CONF_RESET_MINUTES, DEFAULT_RESET_MINUTES)
    )
    options[CONF_WEBHOOK_COUNT] = int(
        options.get(CONF_WEBHOOK_COUNT, DEFAULT_WEBHOOK_COUNT)
    )
    options[CONF_KEYWORD_PARAM] = (
        options.get(CONF_KEYWORD_PARAM) or DEFAULT_KEYWORD_PARAM
    ).strip()
    options[CONF_UNIT_PARAM] = (
        options.get(CONF_UNIT_PARAM) or DEFAULT_UNIT_PARAM
    ).strip()
    options[CONF_FAVORITE_UNIT] = (options.get(CONF_FAVORITE_UNIT) or "").strip()
    options[CONF_API_URL] = (options.get(CONF_API_URL) or DEFAULT_API_URL).strip()
    options[CONF_AVAILABILITY_CALENDARS] = list(
        options.get(CONF_AVAILABILITY_CALENDARS) or []
    )
    for key in (CONF_UNIT_FILTER, CONF_TEST_KEYWORDS, CONF_AVAILABILITY_KEYWORDS):
        options[key] = [
            item.strip() for item in options.get(key) or [] if item and item.strip()
        ]
    return options


class AlamosConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Alamos."""

    VERSION = 1
    MINOR_VERSION = 3

    def __init__(self) -> None:
        """Initialize the flow."""
        self._webhook_ids: list[str] = []

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        if not self._webhook_ids:
            self._webhook_ids = [
                webhook.async_generate_id() for _ in range(MAX_WEBHOOKS)
            ]

        if user_input is not None:
            title = user_input.pop(CONF_NAME).strip() or "Alamos"
            return self.async_create_entry(
                title=title,
                data={
                    CONF_WEBHOOK_ID: self._webhook_ids[0],
                    CONF_ADDITIONAL_WEBHOOK_IDS: self._webhook_ids[1:],
                    CONF_CALENDAR_WEBHOOK_ID: webhook.async_generate_id(),
                },
                options=_clean_options(
                    {
                        CONF_API_KEY: user_input.get(CONF_API_KEY),
                        CONF_SUPPRESS_NOTIFICATION: user_input.get(
                            CONF_SUPPRESS_NOTIFICATION, False
                        ),
                        CONF_RESET_MINUTES: user_input.get(
                            CONF_RESET_MINUTES, DEFAULT_RESET_MINUTES
                        ),
                    }
                ),
                description_placeholders=_webhook_placeholders(
                    self.hass, self._webhook_ids[:1]
                ),
            )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_NAME, default="Alamos"): selector.TextSelector(),
                    vol.Optional(CONF_API_KEY): PASSWORD_SELECTOR,
                    vol.Optional(
                        CONF_SUPPRESS_NOTIFICATION, default=False
                    ): selector.BooleanSelector(),
                    vol.Optional(
                        CONF_RESET_MINUTES, default=DEFAULT_RESET_MINUTES
                    ): MINUTES_SELECTOR,
                }
            ),
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow."""
        return AlamosOptionsFlow()


class AlamosOptionsFlow(OptionsFlow):
    """Handle Alamos options."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(data=_clean_options(user_input))

        data = self.config_entry.data
        placeholders = _webhook_placeholders(
            self.hass, entry_webhook_ids(self.config_entry)
        )
        calendar_webhook_id = data.get(CONF_CALENDAR_WEBHOOK_ID)
        placeholders["calendar_url"] = (
            _webhook_url(self.hass, calendar_webhook_id) if calendar_webhook_id else "-"
        )
        return self.async_show_form(
            step_id="init",
            data_schema=_options_schema(dict(self.config_entry.options)),
            description_placeholders=placeholders,
        )
