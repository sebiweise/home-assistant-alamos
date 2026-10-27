"""Buttons to answer alarms (accept / reject) via the Alamos API."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.const import EntityCategory
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
RESET_ALARM_COUNT = ButtonEntityDescription(
    key="reset_alarm_count",
    translation_key="reset_alarm_count",
    entity_category=EntityCategory.CONFIG,
)


# Home Assistant requires this exact coroutine signature.
async def async_setup_entry(  # NOSONAR
    hass: HomeAssistant,  # NOSONAR
    entry: AlamosConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the buttons, the feedback buttons only with an API key."""
    entities: list[ButtonEntity] = [AlamosResetCountButton(entry, RESET_ALARM_COUNT)]
    if entry.runtime_data.client is not None:
        entities.extend(AlamosFeedbackButton(entry, desc) for desc in BUTTONS)
    async_add_entities(entities)


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
        await async_send_feedback(self._entry, self.entity_description.mode)


class AlamosResetCountButton(AlamosEntity, ButtonEntity):
    """Reset the alarm count and all webhook counts."""

    async def async_added_to_hass(self) -> None:
        """Buttons have no state that depends on the alarm."""

    async def async_press(self) -> None:
        """Reset the counts."""
        self.manager.async_reset_count()
