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
from .const import EVENT_TYPE_CLEARED


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
    ) -> None:
        """Handle a new alarm."""
        state = self.state
        state.active = True
        state.keyword = keyword
        state.unit = unit
        state.data = data
        state.source = source
        state.last_alarm = dt_util.utcnow()
        state.alarm_count += 1
        self._schedule_reset()
        self._notify(event_type, {"keyword": keyword, "unit": unit, "data": data})

    @callback
    def async_clear(self, event_type: str) -> None:
        """Mark the alarm as finished."""
        self._cancel_timer()
        was_active = self.state.active
        self.state.active = False
        self.state.last_cleared = dt_util.utcnow()
        self._notify(event_type if was_active else None)

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
