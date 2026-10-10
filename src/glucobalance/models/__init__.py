"""ORM models. Importing this package registers every table on ``Base.metadata``."""

from glucobalance.models.assistant import (
    AssistantMessage,
    MessageRole,
    StoredSuggestion,
    SuggestionStatus,
)
from glucobalance.models.carbs import CarbEntry, FavouriteMeal
from glucobalance.models.cgm import CGMConnection, CGMSourceKind, GlucoseAlertKind
from glucobalance.models.glucose import GlucoseReading, GlucoseTag, ReadingSource, Trend
from glucobalance.models.hypo import HypoTreatment, HypoTreatmentKind
from glucobalance.models.insulin import DoseKind, InsulinDose, InsulinType
from glucobalance.models.notes import Note
from glucobalance.models.reminders import (
    Notification,
    PushSubscription,
    Reminder,
    ReminderKind,
    RuleType,
)
from glucobalance.models.settings_history import ChangeSource, SettingsChange
from glucobalance.models.sites import (
    BodySide,
    BodySite,
    BodyView,
    SiteBlock,
    SitePreference,
    SitePurpose,
    SiteRegion,
    SiteUse,
)
from glucobalance.models.user import (
    DeliveryMode,
    MonitoringMode,
    SettingsTimeBlock,
    User,
    UserSettings,
)
from glucobalance.units import DisplayUnit

__all__ = [
    "AssistantMessage",
    "BodySide",
    "BodySite",
    "BodyView",
    "CGMConnection",
    "CGMSourceKind",
    "CarbEntry",
    "ChangeSource",
    "DeliveryMode",
    "DisplayUnit",
    "DoseKind",
    "FavouriteMeal",
    "GlucoseAlertKind",
    "GlucoseReading",
    "GlucoseTag",
    "HypoTreatment",
    "HypoTreatmentKind",
    "InsulinDose",
    "InsulinType",
    "MessageRole",
    "MonitoringMode",
    "Note",
    "Notification",
    "PushSubscription",
    "ReadingSource",
    "Reminder",
    "ReminderKind",
    "RuleType",
    "SettingsChange",
    "SettingsTimeBlock",
    "SiteBlock",
    "SitePreference",
    "SitePurpose",
    "SiteRegion",
    "SiteUse",
    "StoredSuggestion",
    "SuggestionStatus",
    "Trend",
    "User",
    "UserSettings",
]
