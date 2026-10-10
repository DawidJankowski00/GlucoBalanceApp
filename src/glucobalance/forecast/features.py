"""The feature pipeline: one row of numbers per CGM reading, and the value 30 minutes later.

A "feature" is one input number for the model. Each row describes the moment of one reading
using only what was known at that moment (nothing from the future leaks in):

- ``glucose``: the reading itself;
- ``delta_5``, ``delta_15``, ``delta_30``: how far glucose moved in the last 5, 15, 30 minutes;
- ``slope_30``: the least-squares trend over the last 30 minutes, in mg/dL per minute;
- ``bend``: the last 15 minutes' change minus the 15 minutes before (is the trend turning?);
- ``iob`` and ``bolus_60``: insulin on board (the linear model of ``glucobalance.iob``) and
  rapid insulin taken in the last hour;
- ``cob`` and ``carbs_60``: carbs on board (absorbed in a straight line over 3 hours) and carbs
  eaten in the last hour;
- ``hour_sin``, ``hour_cos``: the local time of day as a point on a circle, so 23:55 and 00:05
  are close together.

The target is the change from now to the reading 30 minutes ahead. Predicting the change
rather than the value keeps the numbers small and lets "no change" be the natural default.

A row needs readings 5, 15 and 30 minutes back (give or take 2 minutes). With gaps, or with
LibreLinkUp's 15-minute history, there is no row and therefore no forecast.
"""

import bisect
import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, tzinfo

from glucobalance.forecast.history import History

HORIZON = timedelta(minutes=30)
TOLERANCE = timedelta(minutes=2)
INSULIN_ACTION = timedelta(minutes=240)
CARB_ABSORPTION = timedelta(minutes=180)
RECENT = timedelta(minutes=60)

FEATURE_NAMES = (
    "glucose",
    "delta_5",
    "delta_15",
    "delta_30",
    "slope_30",
    "bend",
    "iob",
    "bolus_60",
    "cob",
    "carbs_60",
    "hour_sin",
    "hour_cos",
)
GLUCOSE = FEATURE_NAMES.index("glucose")
SLOPE_30 = FEATURE_NAMES.index("slope_30")


@dataclass(frozen=True, slots=True)
class Sample:
    """One moment: its features, and (when known) the glucose change 30 minutes later."""

    at: datetime
    glucose: int
    features: tuple[float, ...]
    target: float | None  # mg/dL change over the horizon; None when there is no later reading


class _Series:
    """Readings sorted by time, with lookups by moment."""

    def __init__(self, readings: Sequence[tuple[datetime, int]]) -> None:
        ordered = sorted(readings)
        self.times = [at for at, _ in ordered]
        self.values = [value for _, value in ordered]

    def near(self, moment: datetime, tolerance: timedelta = TOLERANCE) -> int | None:
        """The reading closest to ``moment``, if one is within ``tolerance``."""
        i = bisect.bisect_left(self.times, moment)
        best: int | None = None
        best_gap = tolerance
        for j in (i - 1, i):
            if 0 <= j < len(self.times):
                gap = abs(self.times[j] - moment)
                if gap <= best_gap:
                    best, best_gap = self.values[j], gap
        return best

    def window(self, start: datetime, end: datetime) -> list[tuple[float, int]]:
        """(minutes before ``end``, value) for readings with start <= time <= end."""
        lo = bisect.bisect_left(self.times, start)
        hi = bisect.bisect_right(self.times, end)
        return [((end - self.times[k]).total_seconds() / 60, self.values[k]) for k in range(lo, hi)]


class _Events:
    """Carbs or boluses sorted by time."""

    def __init__(self, events: Sequence[tuple[datetime, float]]) -> None:
        ordered = sorted(events)
        self.times = [at for at, _ in ordered]
        self.amounts = [amount for _, amount in ordered]

    def between(self, start: datetime, end: datetime) -> list[tuple[datetime, float]]:
        """Events with start < time <= end."""
        lo = bisect.bisect_right(self.times, start)
        hi = bisect.bisect_right(self.times, end)
        return [(self.times[k], self.amounts[k]) for k in range(lo, hi)]

    def on_board(self, now: datetime, duration: timedelta) -> float:
        """What is left of each event, fading in a straight line to zero over ``duration``."""
        return sum(
            amount * (1 - (now - at) / duration) for at, amount in self.between(now - duration, now)
        )

    def total(self, now: datetime, span: timedelta) -> float:
        return sum(amount for _, amount in self.between(now - span, now))


def slope(points: Sequence[tuple[float, int]]) -> float:
    """Least-squares slope in mg/dL per minute; ``points`` are (minutes ago, value)."""
    if len(points) < 2:
        return 0.0
    xs = [-minutes for minutes, _ in points]
    ys = [float(value) for _, value in points]
    mean_x = sum(xs) / len(xs)
    mean_y = sum(ys) / len(ys)
    spread = sum((x - mean_x) ** 2 for x in xs)
    if spread == 0:
        return 0.0
    return sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=True)) / spread


class FeatureBuilder:
    """Builds rows for one history. Reuse it for many moments of the same history."""

    def __init__(self, history: History, zone: tzinfo = UTC) -> None:
        self.series = _Series(history.readings)
        self.carbs = _Events(history.carbs)
        self.boluses = _Events(history.boluses)
        self.zone = zone

    def features_at(self, index: int) -> tuple[float, ...] | None:
        """The features for reading ``index`` (in time order), or None if history is missing."""
        now = self.series.times[index]
        glucose = self.series.values[index]
        back_5 = self.series.near(now - timedelta(minutes=5))
        back_15 = self.series.near(now - timedelta(minutes=15))
        back_30 = self.series.near(now - timedelta(minutes=30))
        if back_5 is None or back_15 is None or back_30 is None:
            return None
        local = now.astimezone(self.zone)
        angle = (local.hour + local.minute / 60) / 24 * 2 * math.pi
        recent_points = self.series.window(now - timedelta(minutes=30), now)
        return (
            float(glucose),
            float(glucose - back_5),
            float(glucose - back_15),
            float(glucose - back_30),
            slope(recent_points),
            float((glucose - back_15) - (back_15 - back_30)),
            self.boluses.on_board(now, INSULIN_ACTION),
            self.boluses.total(now, RECENT),
            self.carbs.on_board(now, CARB_ABSORPTION),
            self.carbs.total(now, RECENT),
            math.sin(angle),
            math.cos(angle),
        )

    def sample(self, index: int, horizon: timedelta = HORIZON) -> Sample | None:
        features = self.features_at(index)
        if features is None:
            return None
        now = self.series.times[index]
        glucose = self.series.values[index]
        later = self.series.near(now + horizon)
        return Sample(
            at=now,
            glucose=glucose,
            features=features,
            target=None if later is None else float(later - glucose),
        )

    def __len__(self) -> int:
        return len(self.series.times)


def build_samples(
    history: History, zone: tzinfo = UTC, horizon: timedelta = HORIZON
) -> list[Sample]:
    """Every moment of ``history`` that has both features and a known outcome (for training)."""
    builder = FeatureBuilder(history, zone)
    samples = (builder.sample(i, horizon) for i in range(len(builder)))
    return [s for s in samples if s is not None and s.target is not None]


def latest_sample(history: History, zone: tzinfo = UTC) -> Sample | None:
    """The newest reading's features, for a live forecast (its outcome is not known yet)."""
    builder = FeatureBuilder(history, zone)
    if len(builder) == 0:
        return None
    return builder.sample(len(builder) - 1)
