"""The "likely low soon" warning for the live page: loads the data and asks the forecaster.

Like the other services, it takes ``now`` so tests control the clock, and it never commits.
The forecast is skipped (no warning, no error) unless every condition holds:

1. The user has a CGM (the ``forecast_available`` feature flag) and a connection.
2. The newest CGM reading is fresh (at most 15 minutes old, the same rule as dosing).
3. There are readings 5, 15 and 30 minutes before it, so the features can be built.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from glucobalance.cgm.alerts import is_stale
from glucobalance.cgm_service import SOURCE_OF, get_connection
from glucobalance.features import feature_flags
from glucobalance.forecast.features import HORIZON, INSULIN_ACTION, latest_sample
from glucobalance.forecast.history import History
from glucobalance.forecast.models import Forecaster
from glucobalance.forecast.warning import likely_low_soon
from glucobalance.iob import counts_for_iob
from glucobalance.models import User
from glucobalance.repositories import CarbRepository, GlucoseRepository, InsulinRepository

# Enough history for every feature: 30 minutes of readings, 4 hours of insulin and carbs.
LOOKBACK = INSULIN_ACTION


@dataclass(frozen=True, slots=True)
class LowSoon:
    """A forecast that says a low is likely. The predicted value is kept for tests only."""

    reading_at: datetime
    within_minutes: int
    model: str
    predicted_mgdl: float


def load_history(session: Session, user: User, *, now: datetime) -> History | None:
    """The last four hours of CGM readings, rapid boluses and carbs, or None without a CGM."""
    connection = get_connection(session, user)
    if connection is None:
        return None
    source = SOURCE_OF[connection.source]
    start = now - LOOKBACK
    end = now + timedelta(minutes=5)
    readings = [
        (r.measured_at, r.value_mgdl)
        for r in GlucoseRepository(session).between(user.id, start, end)
        if r.source is source and r.measured_at <= now
    ]
    doses = [
        (d.taken_at, float(d.units))
        for d in InsulinRepository(session).between(user.id, start, now)
        if counts_for_iob(d)
    ]
    carbs = [
        (c.eaten_at, float(c.grams)) for c in CarbRepository(session).between(user.id, start, now)
    ]
    return History(readings=tuple(readings), carbs=tuple(carbs), boluses=tuple(doses))


def low_soon(
    session: Session, user: User, forecaster: Forecaster, *, now: datetime
) -> LowSoon | None:
    """A warning if a low looks likely within 30 minutes, otherwise None."""
    settings = user.settings
    if settings is None:
        return None
    if not feature_flags(settings.delivery_mode, settings.monitoring_mode).forecast_available:
        return None
    history = load_history(session, user, now=now)
    if history is None or not history.readings:
        return None
    sample = latest_sample(history, ZoneInfo(settings.timezone))
    if sample is None or is_stale(sample.at, now):
        return None
    predicted = forecaster.predict([sample.features])[0]
    if not likely_low_soon(sample.glucose, predicted):
        return None
    return LowSoon(
        reading_at=sample.at,
        within_minutes=int(HORIZON.total_seconds() // 60),
        model=forecaster.name,
        predicted_mgdl=predicted,
    )
