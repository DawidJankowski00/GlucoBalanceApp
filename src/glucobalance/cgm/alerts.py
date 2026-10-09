"""Live glucose alerts from the CGM stream: which alert applies, and whether to send it now.

Pure functions, no database. ``classify`` looks at the newest reading; ``should_send`` keeps
one episode from turning into a notification on every poll: an alert is sent when it starts
and repeated only after its repeat interval while the episode lasts.

Lows and fast falls are urgent and ignore quiet hours. Highs and lost signal wait.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

from glucobalance.models import GlucoseAlertKind, Trend

# No new value for this long means the data is stale (design rule 4).
STALE_AFTER = timedelta(minutes=15)

REPEAT_AFTER = {
    GlucoseAlertKind.LOW: timedelta(minutes=15),
    GlucoseAlertKind.FALLING_FAST: timedelta(minutes=30),
    GlucoseAlertKind.HIGH: timedelta(hours=2),
    GlucoseAlertKind.STALE: timedelta(hours=1),
}
URGENT = frozenset({GlucoseAlertKind.LOW, GlucoseAlertKind.FALLING_FAST})


@dataclass(frozen=True, slots=True)
class Latest:
    measured_at: datetime
    value_mgdl: int
    trend: Trend | None


def is_stale(last_reading_at: datetime | None, now: datetime) -> bool:
    return last_reading_at is None or now - last_reading_at > STALE_AFTER


def classify(
    latest: Latest | None, *, low_mgdl: int, high_mgdl: int, now: datetime
) -> GlucoseAlertKind | None:
    """The alert in force now, most serious first: stale, low, falling fast, high."""
    if latest is None or is_stale(latest.measured_at, now):
        return GlucoseAlertKind.STALE
    if latest.value_mgdl < low_mgdl:
        return GlucoseAlertKind.LOW
    if latest.trend is Trend.FALLING_FAST:
        return GlucoseAlertKind.FALLING_FAST
    if latest.value_mgdl > high_mgdl:
        return GlucoseAlertKind.HIGH
    return None


def should_send(
    kind: GlucoseAlertKind,
    *,
    previous: GlucoseAlertKind | None,
    previous_sent_at: datetime | None,
    now: datetime,
    quiet: bool,
) -> bool:
    """Send when a new episode starts, or when the same one outlasts its repeat interval.

    During quiet hours only urgent alerts are sent.
    """
    if quiet and kind not in URGENT:
        return False
    if kind is not previous or previous_sent_at is None:
        return True
    return now - previous_sent_at >= REPEAT_AFTER[kind]
