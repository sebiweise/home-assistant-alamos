"""Buttons to answer alarms (accept / reject) via the Alamos API."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import AlamosConfigEntry, async_send_feedback
from .const import FEEDBACK_MODE_ACCEPT, FEEDBACK_MODE_REJECT
from .entity import AlamosEntity


@dataclass(frozen=True, kw_only=True)
class AlamosButtonEntityDescription(ButtonEntityDescription):
    """Describes an Alamos feedback button."""

    mode: str


BUTTONS: tuple[AlamosButtonEntityDescription, ...] = (
    AlamosButtonEntityDescription(
        key="feedback_accept",
        translation_key="feedback_accept",
        mode=FEEDBACK_MODE_ACCEPT,
    ),
    AlamosButtonEntityDescription(
        key="feedback_reject",
        translation_key="feedback_reject",
        mode=FEEDBACK_MODE_REJECT,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AlamosConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the feedback buttons if an API key is configured."""
    if entry.runtime_data.client is None:
        return
    async_add_entities(AlamosFeedbackButton(entry, desc) for desc in BUTTONS)


class AlamosFeedbackButton(AlamosEntity, ButtonEntity):
    """Send feedback for all alarms of the last three minutes."""

    entity_description: AlamosButtonEntityDescription

    def __init__(
        self, entry: AlamosConfigEntry, description: AlamosButtonEntityDescription
    ) -> None:
        """Initialize the button."""
        super().__init__(entry, description)
        self._entry = entry

    async def async_added_to_hass(self) -> None:
        """Buttons have no state that depends on the alarm."""

    async def async_press(self) -> None:
        """Send the feedback."""
        await async_send_feedback(self.hass, self._entry, self.entity_description.mode)
