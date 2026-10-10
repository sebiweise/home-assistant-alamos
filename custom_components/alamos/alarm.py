"""Alarm state shared by all entities of a config entry."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.event import async_call_later
from homeassistant.util import dt as dt_util

from .api import AlamosApiClient
from .const import (
    EVENT_TYPE_CLEARED,
    EVENT_TYPE_TEST_ALARM,
    FEEDBACK_WINDOW,
    MERGE_WINDOW,
)


@dataclass(slots=True)
class AlamosRuntimeData:
    """Runtime data stored on the config entry."""

    manager: AlamosAlarmManager
    client: AlamosApiClient | None


@dataclass(slots=True)
class FeedbackState:
    """Last feedback sent through the API."""

    mode: str
    result: str
    timestamp: datetime


@dataclass(slots=True)
class AlarmState:
    """Current alarm state."""

    active: bool = False
    keyword: str | None = None
    unit: str | None = None
    units: list[str] = field(default_factory=list)
    data: dict[str, Any] = field(default_factory=dict)
    source: str | None = None
    last_alarm: datetime | None = None
    last_cleared: datetime | None = None
    alarm_count: int = 0
    feedback: FeedbackState | None = None


class AlamosAlarmManager:
    """Keep track of incoming alarms and notify entities."""

    def __init__(self, hass: HomeAssistant, reset_minutes: int) -> None:
        """Initialize the manager."""
        self.hass = hass
        self.state = AlarmState()
        self._reset_minutes = reset_minutes
        self._listeners: list[Callable[[], None]] = []
        self._event_listeners: list[Callable[[str, dict[str, Any]], None]] = []
        self._cancel_reset: CALLBACK_TYPE | None = None
        # Last test alarm / recall per kind, to drop the repeated webhooks
        # aPager PRO sends for every alarmed unit.
        self._recent: dict[str, tuple[datetime, str | None]] = {}

    @callback
    def async_add_listener(self, update_callback: Callable[[], None]) -> CALLBACK_TYPE:
        """Listen for state changes."""
        self._listeners.append(update_callback)
        return lambda: self._listeners.remove(update_callback)

    @callback
    def async_add_event_listener(
        self, event_callback: Callable[[str, dict[str, Any]], None]
    ) -> CALLBACK_TYPE:
        """Listen for alarm / cleared events."""
        self._event_listeners.append(event_callback)
        return lambda: self._event_listeners.remove(event_callback)

    @callback
    def _notify(
        self, event_type: str | None = None, data: dict[str, Any] | None = None
    ) -> None:
        # Iterate over copies: listeners may unsubscribe while being called.
        for listener in self._listeners.copy():
            listener()
        if event_type is not None:
            for listener in self._event_listeners.copy():
                listener(event_type, data or {})

    @callback
    def async_alarm(
        self,
        keyword: str | None,
        unit: str | None,
        data: dict[str, Any],
        source: str,
        event_type: str,
    ) -> bool:
        """Handle a new alarm.

        Returns False if the webhook was merged into the active alarm because
        aPager PRO sent it for another unit of the same alarm.
        """
        state = self.state
        now = dt_util.utcnow()
        if (
            state.active
            and state.last_alarm is not None
            and now - state.last_alarm <= MERGE_WINDOW
            and _same_keyword(state.keyword, keyword)
        ):
            if unit and unit not in state.units:
                state.units.append(unit)
            state.unit = state.unit or unit
            self._notify()
            return False

        state.active = True
        state.keyword = keyword
        state.unit = unit
        state.units = [unit] if unit else []
        state.data = data
        state.source = source
        state.last_alarm = now
        state.alarm_count += 1
        self._schedule_reset()
        self._notify(event_type, _event_data(keyword, unit, data, test=False))
        return True

    @callback
    def async_test_alarm(
        self, keyword: str | None, unit: str | None, data: dict[str, Any]
    ) -> bool:
        """Handle a test alarm: fire events but keep the alarm state untouched.

        Returns False if it repeats the last test alarm (another unit).
        """
        if self._is_repeat(EVENT_TYPE_TEST_ALARM, keyword):
            return False
        self._notify(EVENT_TYPE_TEST_ALARM, _event_data(keyword, unit, data, test=True))
        return True

    @callback
    def async_recall(self, data: dict[str, Any]) -> bool:
        """Handle a recall: end the alarm and always report it.

        Returns False if it repeats the last recall (another unit).
        """
        if self._is_repeat("recall", data.get("keyword")):
            return False
        self.async_clear(EVENT_TYPE_CLEARED, data, force_event=True)
        return True

    @callback
    def _is_repeat(self, kind: str, keyword: str | None) -> bool:
        now = dt_util.utcnow()
        last = self._recent.get(kind)
        self._recent[kind] = (now, keyword)
        return (
            last is not None
            and now - last[0] <= MERGE_WINDOW
            and _same_keyword(last[1], keyword)
        )

    @property
    def feedback_deadline(self) -> datetime | None:
        """Return until when the last alarm can be answered through the API."""
        if self.state.last_alarm is None:
            return None
        return self.state.last_alarm + FEEDBACK_WINDOW

    @callback
    def async_clear(
        self,
        event_type: str,
        data: dict[str, Any] | None = None,
        *,
        force_event: bool = False,
    ) -> None:
        """Mark the alarm as finished.

        The event is only fired if an alarm was active, unless ``force_event``
        is set (e.g. for an explicit recall which should always be reported).
        """
        self._cancel_timer()
        was_active = self.state.active
        self.state.active = False
        self.state.last_cleared = dt_util.utcnow()
        self._notify(event_type if was_active or force_event else None, data)

    @callback
    def async_feedback(self, mode: str, result: str) -> None:
        """Store the result of a feedback request."""
        self.state.feedback = FeedbackState(
            mode=mode, result=result, timestamp=dt_util.utcnow()
        )
        self._notify()

    @callback
    def async_restore(
        self, alarm_count: int | None = None, last_alarm: datetime | None = None
    ) -> None:
        """Restore values which should survive a restart."""
        if alarm_count is not None and self.state.alarm_count == 0:
            self.state.alarm_count = alarm_count
        if last_alarm is not None and self.state.last_alarm is None:
            self.state.last_alarm = last_alarm

    @callback
    def async_shutdown(self) -> None:
        """Cancel pending timers."""
        self._cancel_timer()

    @callback
    def _schedule_reset(self) -> None:
        self._cancel_timer()
        if self._reset_minutes <= 0:
            return
        self._cancel_reset = async_call_later(
            self.hass,
            timedelta(minutes=self._reset_minutes),
            self._handle_timeout,
        )

    @callback
    def _handle_timeout(self, _now: datetime) -> None:
        self._cancel_reset = None
        self.async_clear(EVENT_TYPE_CLEARED)

    @callback
    def _cancel_timer(self) -> None:
        if self._cancel_reset is not None:
            self._cancel_reset()
            self._cancel_reset = None


def _same_keyword(first: str | None, second: str | None) -> bool:
    """Return True if two keywords are equal (case-insensitive)."""
    if first is None or second is None:
        return first is None and second is None
    return first.casefold() == second.casefold()


def _event_data(
    keyword: str | None, unit: str | None, data: dict[str, Any], *, test: bool
) -> dict[str, Any]:
    """Build the data passed to event listeners."""
    return {
        "keyword": keyword,
        "unit": unit,
        "units": [unit] if unit else [],
        "data": data,
        "test": test,
        "feedback_deadline": (dt_util.utcnow() + FEEDBACK_WINDOW).isoformat(),
    }
