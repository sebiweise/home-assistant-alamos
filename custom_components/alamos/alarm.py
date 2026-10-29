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
class WebhookInfo:
    """Last webhook call as received, for troubleshooting."""

    timestamp: datetime
    webhook: int
    method: str
    data: dict[str, Any]
    result: str


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
    webhook_counts: dict[int, int] = field(default_factory=dict)
    alarm_webhooks: set[int] = field(default_factory=set)
    feedback: FeedbackState | None = None
    last_webhook: WebhookInfo | None = None


class AlamosAlarmManager:
    """Keep track of incoming alarms and notify entities."""

    def __init__(
        self,
        hass: HomeAssistant,
        reset_minutes: int,
        favorite_unit: str | None = None,
    ) -> None:
        """Initialize the manager."""
        self.hass = hass
        self.state = AlarmState()
        self._reset_minutes = reset_minutes
        self._favorite_unit = favorite_unit
        self._listeners: list[Callable[[], None]] = []
        self._event_listeners: list[Callable[[str, dict[str, Any]], None]] = []
        self._webhook_listeners: list[Callable[[int, str, dict[str, Any]], None]] = []
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
    def async_add_webhook_listener(
        self, webhook_callback: Callable[[int, str, dict[str, Any]], None]
    ) -> CALLBACK_TYPE:
        """Listen for alarm / cleared events per webhook.

        Unlike the events of the entry, they are also fired for a webhook
        whose call was merged into the active alarm.
        """
        self._webhook_listeners.append(webhook_callback)
        return lambda: self._webhook_listeners.remove(webhook_callback)

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
    def _notify_webhook(
        self, webhook: int, event_type: str, data: dict[str, Any]
    ) -> None:
        """Pass an event of one webhook to the webhook listeners."""
        for listener in self._webhook_listeners.copy():
            listener(webhook, event_type, data)

    @callback
    def async_alarm(
        self,
        keyword: str | None,
        unit: str | None,
        data: dict[str, Any],
        source: str,
        event_type: str,
        webhook: int,
    ) -> bool:
        """Handle a new alarm.

        Returns False if the webhook was merged into the active alarm because
        aPager PRO sent it for another unit of the same alarm. Webhooks without
        a keyword (e.g. a unit whose webhook does not transmit it) are merged
        too, so they cannot overwrite the keyword of the running alarm.
        Every webhook counts an alarm once, merged or not.
        """
        state = self.state
        now = dt_util.utcnow()
        if (
            state.active
            and state.last_alarm is not None
            and now - state.last_alarm <= MERGE_WINDOW
            and (
                keyword is None
                or state.keyword is None
                or _same_keyword(state.keyword, keyword)
            )
        ):
            state.keyword = state.keyword or keyword
            if unit and unit not in state.units:
                state.units = self._sort_units([*state.units, unit])
            state.unit = state.units[0] if state.units else None
            counted = self._count_alarm(webhook)
            self._notify()
            if counted:
                self._notify_webhook(
                    webhook,
                    event_type,
                    _event_data(state.keyword, unit, data, test=False, webhook=webhook),
                )
            return False

        state.active = True
        state.keyword = keyword
        state.unit = unit
        state.units = [unit] if unit else []
        state.data = data
        state.source = source
        state.last_alarm = now
        state.alarm_count += 1
        state.alarm_webhooks = set()
        self._count_alarm(webhook)
        self._schedule_reset()
        event_data = _event_data(keyword, unit, data, test=False, webhook=webhook)
        self._notify(event_type, event_data)
        self._notify_webhook(webhook, event_type, event_data)
        return True

    def _count_alarm(self, webhook: int) -> bool:
        """Count the alarm for a webhook, return False if it already was."""
        state = self.state
        if webhook in state.alarm_webhooks:
            return False
        state.alarm_webhooks.add(webhook)
        state.webhook_counts[webhook] = state.webhook_counts.get(webhook, 0) + 1
        return True

    def _sort_units(self, units: list[str]) -> list[str]:
        """Put the favorite unit first, keep the order of the others."""
        if not self._favorite_unit:
            return units
        favorite = self._favorite_unit.casefold()
        return sorted(units, key=lambda unit: unit.casefold() != favorite)

    @callback
    def async_test_alarm(
        self,
        keyword: str | None,
        unit: str | None,
        data: dict[str, Any],
        webhook: int,
    ) -> bool:
        """Handle a test alarm: fire events but keep the alarm state untouched.

        Returns False if it repeats the last test alarm (another unit).
        """
        event_data = _event_data(keyword, unit, data, test=True, webhook=webhook)
        if reported := not self._is_repeat(EVENT_TYPE_TEST_ALARM, keyword):
            self._notify(EVENT_TYPE_TEST_ALARM, event_data)
        if not self._is_repeat(f"{EVENT_TYPE_TEST_ALARM}_{webhook}", keyword):
            self._notify_webhook(webhook, EVENT_TYPE_TEST_ALARM, event_data)
        return reported

    @callback
    def async_recall(self, data: dict[str, Any], webhook: int) -> bool:
        """Handle a recall: end the alarm and always report it.

        Returns False if it repeats the last recall (another unit).
        """
        keyword = data.get("keyword")
        cleared: set[int] = set()
        if reported := not self._is_repeat("recall", keyword):
            if self.state.active:
                cleared = set(self.state.alarm_webhooks)
            self.async_clear(EVENT_TYPE_CLEARED, data, force_event=True)
        # Webhooks already cleared with the alarm drop their own recall.
        for number in cleared:
            self._is_repeat(f"recall_{number}", keyword)
        if webhook not in cleared and not self._is_repeat(f"recall_{webhook}", keyword):
            self._notify_webhook(webhook, EVENT_TYPE_CLEARED, data)
        return reported

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
        Every webhook which reported the active alarm gets the event too.
        """
        self._cancel_timer()
        was_active = self.state.active
        self.state.active = False
        self.state.last_cleared = dt_util.utcnow()
        self._notify(event_type if was_active or force_event else None, data)
        if was_active:
            for webhook in sorted(self.state.alarm_webhooks):
                self._notify_webhook(webhook, event_type, data or {})

    @callback
    def async_feedback(self, mode: str, result: str) -> None:
        """Store the result of a feedback request."""
        self.state.feedback = FeedbackState(
            mode=mode, result=result, timestamp=dt_util.utcnow()
        )
        self._notify()

    @callback
    def async_webhook_received(
        self, webhook: int, method: str, data: dict[str, Any], result: str
    ) -> None:
        """Store the last webhook call, whatever it was used for."""
        self.state.last_webhook = WebhookInfo(
            timestamp=dt_util.utcnow(),
            webhook=webhook,
            method=method,
            data=data,
            result=result,
        )
        self._notify()

    @callback
    def async_reset_count(self, webhook: int | None = None) -> None:
        """Reset the alarm count and all webhook counts, or one webhook count."""
        if webhook is None:
            self.state.alarm_count = 0
            self.state.webhook_counts.clear()
        else:
            self.state.webhook_counts.pop(webhook, None)
        self._notify()

    @callback
    def async_restore(
        self,
        alarm_count: int | None = None,
        last_alarm: datetime | None = None,
        webhook: int | None = None,
    ) -> None:
        """Restore values which should survive a restart.

        With ``webhook``, ``alarm_count`` is the count of that webhook.
        """
        if alarm_count is not None:
            if webhook is not None:
                self.state.webhook_counts.setdefault(webhook, alarm_count)
            elif self.state.alarm_count == 0:
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
    keyword: str | None,
    unit: str | None,
    data: dict[str, Any],
    *,
    test: bool,
    webhook: int,
) -> dict[str, Any]:
    """Build the data passed to event listeners."""
    return {
        "keyword": keyword,
        "unit": unit,
        "units": [unit] if unit else [],
        "data": data,
        "test": test,
        "webhook": webhook,
        "feedback_deadline": (dt_util.utcnow() + FEEDBACK_WINDOW).isoformat(),
    }
