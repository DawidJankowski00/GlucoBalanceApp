"""The one interface the rest of the app knows for continuous glucose monitors.

A ``CGMSource`` answers a single question: which readings have arrived since a moment? Each
adapter (the simulator, LibreLinkUp, later perhaps Nightscout) hides how it gets them. The
import service and the polling job only ever see ``CGMReading`` values and the errors below.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from glucobalance.models import Trend


@dataclass(frozen=True, slots=True)
class CGMReading:
    """One sensor value: UTC time, mg/dL and, when the sensor gives one, the trend arrow."""

    measured_at: datetime
    value_mgdl: int
    trend: Trend | None = None


class CGMError(Exception):
    """The source could not deliver readings. The message is safe to show and to log."""


class CGMAuthError(CGMError):
    """The login was refused (wrong e-mail or password, or an account step is pending)."""


class CGMRateLimited(CGMError):
    """The server asked us to slow down (HTTP 429). Try again later, not on the next tick."""


class CGMSource(Protocol):
    def fetch_readings(self, since: datetime) -> Sequence[CGMReading]:
        """Readings measured after ``since`` (UTC), oldest first."""
        ...


def trend_from_rate(mgdl_per_minute: float) -> Trend:
    """Classify a rate of change like a CGM trend arrow (the bands Libre and Dexcom use)."""
    if mgdl_per_minute < -2:
        return Trend.FALLING_FAST
    if mgdl_per_minute < -1:
        return Trend.FALLING
    if mgdl_per_minute <= 1:
        return Trend.STEADY
    if mgdl_per_minute <= 2:
        return Trend.RISING
    return Trend.RISING_FAST
