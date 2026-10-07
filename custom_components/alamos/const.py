"""Constants for the Alamos integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "alamos"

# Alamos availability API (aPager PRO "Externer Zugriff" / Smart Home)
DEFAULT_API_URL: Final = "https://alamos-backend.ey.r.appspot.com"
FEEDBACK_PATH: Final = "/fe2/feedback/user/external"

FEEDBACK_MODE_ACCEPT: Final = "accept"
FEEDBACK_MODE_REJECT: Final = "reject"
FEEDBACK_MODES: Final = [FEEDBACK_MODE_ACCEPT, FEEDBACK_MODE_REJECT]

# Config entry data / options
CONF_API_KEY: Final = "api_key"
CONF_API_URL: Final = "api_url"
CONF_WEBHOOK_ID: Final = "webhook_id"
CONF_SUPPRESS_NOTIFICATION: Final = "suppress_notification"
CONF_RESET_MINUTES: Final = "reset_minutes"
CONF_KEYWORD_PARAM: Final = "keyword_param"
CONF_UNIT_PARAM: Final = "unit_param"

DEFAULT_RESET_MINUTES: Final = 30
DEFAULT_KEYWORD_PARAM: Final = "keyword"
DEFAULT_UNIT_PARAM: Final = "unit"

# Query / body parameter used to tell the integration which event happened.
# AMweb can call one URL on a new alarm and another one when no alarm is open
# anymore, so the second URL gets "?event=clear" appended.
WEBHOOK_EVENT_PARAM: Final = "event"
WEBHOOK_CLEAR_VALUES: Final = frozenset({"clear", "reset", "end", "idle", "off"})

# Events fired on the Home Assistant bus
EVENT_ALARM: Final = "alamos_alarm"
EVENT_ALARM_CLEARED: Final = "alamos_alarm_cleared"

# Event entity event types
EVENT_TYPE_ALARM: Final = "alarm"
EVENT_TYPE_CLEARED: Final = "cleared"

# Services
SERVICE_SEND_FEEDBACK: Final = "send_feedback"
SERVICE_RESET_ALARM: Final = "reset_alarm"
ATTR_CONFIG_ENTRY_ID: Final = "config_entry_id"
ATTR_MODE: Final = "mode"
ATTR_SUPPRESS_NOTIFICATION: Final = "suppress_notification"

ATTR_KEYWORD: Final = "keyword"
ATTR_UNIT: Final = "unit"
ATTR_DATA: Final = "data"
ATTR_SOURCE: Final = "source"
