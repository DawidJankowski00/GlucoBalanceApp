"""ORM models. Importing this package registers every table on ``Base.metadata``."""

from glucobalance.models.carbs import CarbEntry
from glucobalance.models.glucose import GlucoseReading, GlucoseTag, ReadingSource, Trend
from glucobalance.models.insulin import DoseKind, InsulinDose, InsulinType
from glucobalance.models.notes import Note
from glucobalance.models.reminders import Reminder, ReminderKind
from glucobalance.models.sites import BodySide, BodySite, BodyView, SitePurpose, SiteRegion, SiteUse
from glucobalance.models.user import (
    DeliveryMode,
    DisplayUnit,
    MonitoringMode,
    SettingsTimeBlock,
    User,
    UserSettings,
)

__all__ = [
    "BodySide",
    "BodySite",
    "BodyView",
    "CarbEntry",
    "DeliveryMode",
    "DisplayUnit",
    "DoseKind",
    "GlucoseReading",
    "GlucoseTag",
    "InsulinDose",
    "InsulinType",
    "MonitoringMode",
    "Note",
    "ReadingSource",
    "Reminder",
    "ReminderKind",
    "SettingsTimeBlock",
    "SitePurpose",
    "SiteRegion",
    "SiteUse",
    "Trend",
    "User",
    "UserSettings",
]
