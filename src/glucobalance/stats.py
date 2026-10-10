"""Glucose statistics for a period: time in range, mean, variability and GMI.

Everything here is a pure function of the readings it is given, in mg/dL. The figures follow
the international consensus on CGM metrics (Battelino et al., 2019); ADR 0016 lists the choices.
"""

import statistics
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import timedelta
from zoneinfo import ZoneInfo

from glucobalance.models import GlucoseReading, MonitoringMode

VERY_LOW_MGDL = 54
VERY_HIGH_MGDL = 250
# The LibreLinkUp history has one point every 15 minutes, so a day holds at most 96 of them.
SLOT_MINUTES = 15
SLOTS_PER_DAY = 24 * 60 // SLOT_MINUTES
MIN_DAYS = 14
MIN_COVERAGE = 70.0
# Fewer logged readings a day than this and a glucometer user's figures are only a hint.
MIN_MANUAL_PER_DAY = 2
# Two low readings this close together belong to the same low episode.
EPISODE_GAP = timedelta(hours=1)


@dataclass(frozen=True, slots=True)
class GlucoseStats:
    """The headline figures for one period. Percentages are 0 to 100."""

    count: int
    mean: float
    sd: float
    cv: float  # coefficient of variation, percent
    gmi: float  # glucose management indicator, percent (an HbA1c estimate)
    very_low: float  # below 54 mg/dL
    below: float  # below the target range (includes very low)
    in_range: float
    above: float  # above the target range (includes very high)
    very_high: float  # above 250 mg/dL
    coverage: float | None  # share of 15-minute slots with a reading (CGM only)
    warning: str | None


@dataclass(frozen=True, slots=True)
class PeriodAverage:
    """The average of the readings taken in one part of the day."""

    name: str
    count: int
    mean: float | None


def _percent(part: int, whole: int) -> float:
    return part / whole * 100


def _coverage(readings: Sequence[GlucoseReading], days: int) -> float:
    slots = {int(r.measured_at.timestamp()) // (SLOT_MINUTES * 60) for r in readings}
    return min(100.0, len(slots) / (days * SLOTS_PER_DAY) * 100)


def _warning(count: int, days: int, coverage: float | None, mode: MonitoringMode) -> str | None:
    notes: list[str] = []
    if mode is MonitoringMode.CGM:
        if days < MIN_DAYS:
            notes.append(f"Only {days} days selected; at least {MIN_DAYS} days are recommended.")
        if coverage is not None and coverage < MIN_COVERAGE:
            notes.append(
                f"The sensor covers {coverage:.0f}% of the period; at least "
                f"{MIN_COVERAGE:.0f}% is recommended."
            )
    elif count < MIN_MANUAL_PER_DAY * days:
        notes.append(
            f"Too few readings (under {MIN_MANUAL_PER_DAY} a day), so these figures may not "
            "show your real pattern."
        )
    return " ".join(notes) or None


def compute_stats(
    readings: Sequence[GlucoseReading],
    *,
    low: int,
    high: int,
    days: int,
    mode: MonitoringMode,
) -> GlucoseStats | None:
    """The statistics for ``readings`` over a period of ``days``; ``None`` without readings."""
    if not readings:
        return None
    values = [r.value_mgdl for r in readings]
    count = len(values)
    mean = statistics.fmean(values)
    sd = statistics.stdev(values) if count > 1 else 0.0
    coverage = _coverage(readings, days) if mode is MonitoringMode.CGM else None
    return GlucoseStats(
        count=count,
        mean=mean,
        sd=sd,
        cv=sd / mean * 100,
        gmi=3.31 + 0.02392 * mean,
        very_low=_percent(sum(v < VERY_LOW_MGDL for v in values), count),
        below=_percent(sum(v < low for v in values), count),
        in_range=_percent(sum(low <= v <= high for v in values), count),
        above=_percent(sum(v > high for v in values), count),
        very_high=_percent(sum(v > VERY_HIGH_MGDL for v in values), count),
        coverage=coverage,
        warning=_warning(count, days, coverage, mode),
    )


def low_episodes(readings: Iterable[GlucoseReading], *, limit: int) -> int:
    """How many separate lows there were: low readings within an hour count as one episode."""
    lows = sorted(r.measured_at for r in readings if r.value_mgdl < limit)
    episodes = 0
    previous = None
    for moment in lows:
        if previous is None or moment - previous > EPISODE_GAP:
            episodes += 1
        previous = moment
    return episodes


# (name, first hour, last hour + 1) in local time
_PERIODS = (("Night", 0, 6), ("Morning", 6, 11), ("Afternoon", 11, 17), ("Evening", 17, 24))


def time_of_day_averages(readings: Iterable[GlucoseReading], zone: ZoneInfo) -> list[PeriodAverage]:
    """The mean per part of the local day, for users with too few readings for an AGP."""
    grouped: dict[str, list[int]] = defaultdict(list)
    for reading in readings:
        hour = reading.measured_at.astimezone(zone).hour
        for name, start, end in _PERIODS:
            if start <= hour < end:
                grouped[name].append(reading.value_mgdl)
    return [
        PeriodAverage(
            name,
            len(grouped[name]),
            statistics.fmean(grouped[name]) if grouped[name] else None,
        )
        for name, _, _ in _PERIODS
    ]
