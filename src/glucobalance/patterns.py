"""Rule-based pattern detectors over a period of readings.

Each detector is a pure function that returns a ``Finding`` (with the readings that support it)
or ``None``. There is no statistics model and no AI here: a pattern is a fixed rule, with the
thresholds named below, so a finding can always be explained and re-checked by hand. Stage 8
turns these findings into capped suggestions; this module only describes what happened.
"""

import statistics
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import StrEnum
from zoneinfo import ZoneInfo

from glucobalance.models import CarbEntry, GlucoseReading, GlucoseTag

LOW_MGDL = 70  # the hypo limit used everywhere in the app (design rule 4)

NIGHT_START_HOUR = 0
NIGHT_END_HOUR = 6
MIN_LOW_NIGHTS = 3

BREAKFAST_START_HOUR = 5
BREAKFAST_END_HOUR = 11
AFTER_MEAL_FROM = timedelta(hours=1)  # the rise is judged from one hour after eating...
AFTER_MEAL_TO = timedelta(hours=3)  # ...to three hours after
MIN_BREAKFAST_DAYS = 4  # days with a breakfast and a reading in the window
MIN_HIGH_DAYS = 3
MIN_HIGH_SHARE = 0.5  # at least half of those days must peak above range

FASTING_GOAL_MGDL = 130
FASTING_FALLBACK_START_HOUR = 5  # untagged readings from 05:00 to 08:00 stand in for fasting
FASTING_FALLBACK_END_HOUR = 8
MIN_FASTING_DAYS = 5


class PatternKind(StrEnum):
    NIGHT_LOWS = "night_lows"
    POST_BREAKFAST_HIGHS = "post_breakfast_highs"
    HIGH_FASTING = "high_fasting"


@dataclass(frozen=True, slots=True)
class Evidence:
    """One reading that supports a finding."""

    measured_at: datetime
    value_mgdl: int


@dataclass(frozen=True, slots=True)
class Finding:
    """A pattern found in the data, with the readings that show it.

    ``headline_mgdl`` is the one glucose value that sums it up (the lowest night low, or the
    median peak or fasting value); it is shown in the user's unit, so ``detail`` has no glucose
    numbers in it.
    """

    kind: PatternKind
    title: str
    detail: str
    headline_mgdl: float
    evidence: tuple[Evidence, ...]


def _evidence(reading: GlucoseReading) -> Evidence:
    return Evidence(reading.measured_at, reading.value_mgdl)


def _by_local_day(
    readings: Sequence[GlucoseReading], zone: ZoneInfo
) -> dict[date, list[GlucoseReading]]:
    days: dict[date, list[GlucoseReading]] = defaultdict(list)
    for reading in sorted(readings, key=lambda r: r.measured_at):
        days[reading.measured_at.astimezone(zone).date()].append(reading)
    return days


def night_lows(readings: Sequence[GlucoseReading], zone: ZoneInfo) -> Finding | None:
    """Lows between midnight and 06:00 on at least three different nights."""
    lowest: dict[date, GlucoseReading] = {}
    for reading in readings:
        local = reading.measured_at.astimezone(zone)
        if reading.value_mgdl >= LOW_MGDL or not NIGHT_START_HOUR <= local.hour < NIGHT_END_HOUR:
            continue
        current = lowest.get(local.date())
        if current is None or reading.value_mgdl < current.value_mgdl:
            lowest[local.date()] = reading
    if len(lowest) < MIN_LOW_NIGHTS:
        return None
    nights = [lowest[day] for day in sorted(lowest)]
    return Finding(
        kind=PatternKind.NIGHT_LOWS,
        title="Repeated night lows",
        detail=(
            f"Glucose went below {LOW_MGDL} mg/dL between midnight and 06:00 on "
            f"{len(nights)} nights in this period."
        ),
        headline_mgdl=min(r.value_mgdl for r in nights),
        evidence=tuple(_evidence(r) for r in nights),
    )


def _breakfasts(carbs: Sequence[CarbEntry], zone: ZoneInfo) -> dict[date, datetime]:
    """The first carb entry of each local morning (05:00 to 11:00)."""
    first: dict[date, datetime] = {}
    for entry in sorted(carbs, key=lambda c: c.eaten_at):
        local = entry.eaten_at.astimezone(zone)
        if BREAKFAST_START_HOUR <= local.hour < BREAKFAST_END_HOUR:
            first.setdefault(local.date(), entry.eaten_at)
    return first


def post_breakfast_highs(
    readings: Sequence[GlucoseReading],
    carbs: Sequence[CarbEntry],
    zone: ZoneInfo,
    *,
    high: int,
) -> Finding | None:
    """The peak one to three hours after breakfast is above range on at least half of the days."""
    ordered = sorted(readings, key=lambda r: r.measured_at)
    peaks: list[GlucoseReading] = []
    for eaten in _breakfasts(carbs, zone).values():
        window = [
            r for r in ordered if eaten + AFTER_MEAL_FROM <= r.measured_at <= eaten + AFTER_MEAL_TO
        ]
        if window:
            peaks.append(max(window, key=lambda r: r.value_mgdl))
    high_peaks = [p for p in peaks if p.value_mgdl > high]
    if (
        len(peaks) < MIN_BREAKFAST_DAYS
        or len(high_peaks) < MIN_HIGH_DAYS
        or len(high_peaks) / len(peaks) < MIN_HIGH_SHARE
    ):
        return None
    return Finding(
        kind=PatternKind.POST_BREAKFAST_HIGHS,
        title="Highs after breakfast",
        detail=(
            f"Glucose peaked above your target range in the 1 to 3 hours after breakfast on "
            f"{len(high_peaks)} of {len(peaks)} days."
        ),
        headline_mgdl=statistics.median(p.value_mgdl for p in high_peaks),
        evidence=tuple(_evidence(p) for p in high_peaks),
    )


def high_fasting(readings: Sequence[GlucoseReading], zone: ZoneInfo) -> Finding | None:
    """The fasting value is above the fasting goal on at least half of the days.

    A day's fasting value is its first reading tagged fasting. Without a tag, the first reading
    between 05:00 and 08:00 stands in, so CGM users (who do not tag readings) are covered.
    """
    values: list[GlucoseReading] = []
    for day_readings in _by_local_day(readings, zone).values():
        tagged = [r for r in day_readings if r.tag is GlucoseTag.FASTING]
        early = [
            r
            for r in day_readings
            if FASTING_FALLBACK_START_HOUR
            <= r.measured_at.astimezone(zone).hour
            < FASTING_FALLBACK_END_HOUR
        ]
        chosen = tagged or early
        if chosen:
            values.append(chosen[0])
    high_values = [r for r in values if r.value_mgdl > FASTING_GOAL_MGDL]
    if len(values) < MIN_FASTING_DAYS or len(high_values) / len(values) < MIN_HIGH_SHARE:
        return None
    return Finding(
        kind=PatternKind.HIGH_FASTING,
        title="High fasting values",
        detail=(
            f"The fasting value was above {FASTING_GOAL_MGDL} mg/dL on "
            f"{len(high_values)} of {len(values)} days."
        ),
        headline_mgdl=statistics.median(r.value_mgdl for r in values),
        evidence=tuple(_evidence(r) for r in high_values),
    )


def detect_patterns(
    readings: Sequence[GlucoseReading],
    carbs: Sequence[CarbEntry],
    zone: ZoneInfo,
    *,
    high: int,
) -> list[Finding]:
    """Every pattern found in the data, in a fixed order."""
    found = (
        night_lows(readings, zone),
        post_breakfast_highs(readings, carbs, zone, high=high),
        high_fasting(readings, zone),
    )
    return [finding for finding in found if finding is not None]
