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

from .const import (
    CONF_API_KEY,
    CONF_API_URL,
    CONF_KEYWORD_PARAM,
    CONF_RESET_MINUTES,
    CONF_SUPPRESS_NOTIFICATION,
    CONF_UNIT_PARAM,
    CONF_WEBHOOK_ID,
    DEFAULT_API_URL,
    DEFAULT_KEYWORD_PARAM,
    DEFAULT_RESET_MINUTES,
    DEFAULT_UNIT_PARAM,
    DOMAIN,
    WEBHOOK_EVENT_PARAM,
)

PASSWORD_SELECTOR = selector.TextSelector(
    selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
)
URL_SELECTOR = selector.TextSelector(
    selector.TextSelectorConfig(type=selector.TextSelectorType.URL)
)
MINUTES_SELECTOR = selector.NumberSelector(
    selector.NumberSelectorConfig(
        min=0,
        max=1440,
        step=1,
        unit_of_measurement="min",
        mode=selector.NumberSelectorMode.BOX,
    )
)


def _webhook_placeholders(hass: HomeAssistant, webhook_id: str) -> dict[str, str]:
    try:
        url = webhook.async_generate_url(hass, webhook_id)
    except HomeAssistantError:  # no external/internal URL configured yet
        url = webhook.async_generate_path(webhook_id)
    return {
        "webhook_url": url,
        "webhook_clear_url": f"{url}?{WEBHOOK_EVENT_PARAM}=clear",
    }


def _options_schema(options: dict[str, Any]) -> vol.Schema:
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
                CONF_KEYWORD_PARAM,
                default=options.get(CONF_KEYWORD_PARAM, DEFAULT_KEYWORD_PARAM),
            ): selector.TextSelector(),
            vol.Optional(
                CONF_UNIT_PARAM,
                default=options.get(CONF_UNIT_PARAM, DEFAULT_UNIT_PARAM),
            ): selector.TextSelector(),
            vol.Optional(
                CONF_API_URL,
                default=options.get(CONF_API_URL, DEFAULT_API_URL),
            ): URL_SELECTOR,
        }
    )


def _clean_options(user_input: dict[str, Any]) -> dict[str, Any]:
    options = dict(user_input)
    options[CONF_API_KEY] = (options.get(CONF_API_KEY) or "").strip()
    options[CONF_RESET_MINUTES] = int(
        options.get(CONF_RESET_MINUTES, DEFAULT_RESET_MINUTES)
    )
    options[CONF_KEYWORD_PARAM] = (
        options.get(CONF_KEYWORD_PARAM) or DEFAULT_KEYWORD_PARAM
    ).strip()
    options[CONF_UNIT_PARAM] = (
        options.get(CONF_UNIT_PARAM) or DEFAULT_UNIT_PARAM
    ).strip()
    options[CONF_API_URL] = (options.get(CONF_API_URL) or DEFAULT_API_URL).strip()
    return options


class AlamosConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Alamos."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the flow."""
        self._webhook_id: str | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        if self._webhook_id is None:
            self._webhook_id = webhook.async_generate_id()

        if user_input is not None:
            title = user_input.pop(CONF_NAME).strip() or "Alamos"
            return self.async_create_entry(
                title=title,
                data={CONF_WEBHOOK_ID: self._webhook_id},
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
                    self.hass, self._webhook_id
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

        return self.async_show_form(
            step_id="init",
            data_schema=_options_schema(dict(self.config_entry.options)),
            description_placeholders=_webhook_placeholders(
                self.hass, self.config_entry.data[CONF_WEBHOOK_ID]
            ),
        )
