"""ORM models. Importing this package registers every table on ``Base.metadata``."""

from glucobalance.models.carbs import CarbEntry, FavouriteMeal
from glucobalance.models.glucose import GlucoseReading, GlucoseTag, ReadingSource, Trend
from glucobalance.models.hypo import HypoTreatment, HypoTreatmentKind
from glucobalance.models.insulin import DoseKind, InsulinDose, InsulinType
from glucobalance.models.notes import Note
from glucobalance.models.reminders import Reminder, ReminderKind
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
    "BodySide",
    "BodySite",
    "BodyView",
    "CarbEntry",
    "ChangeSource",
    "DeliveryMode",
    "DisplayUnit",
    "DoseKind",
    "FavouriteMeal",
    "GlucoseReading",
    "GlucoseTag",
    "HypoTreatment",
    "HypoTreatmentKind",
    "InsulinDose",
    "InsulinType",
    "MonitoringMode",
    "Note",
    "ReadingSource",
    "Reminder",
    "ReminderKind",
    "SettingsChange",
    "SettingsTimeBlock",
    "SiteBlock",
    "SitePreference",
    "SitePurpose",
    "SiteRegion",
    "SiteUse",
    "Trend",
    "User",
    "UserSettings",
]
