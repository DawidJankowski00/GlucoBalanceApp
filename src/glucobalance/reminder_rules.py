"""When is a reminder due? Pure functions, no database, no clock.

Three rule types (see ``RuleType``): every N days, daily at a time, and after an event.
Quiet hours and snooze then only ever move a due time *later*.

All datetimes are timezone-aware. Wall-clock times ("08:00") are read in the user's time
zone, so a reminder keeps its local time when the clocks change.
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo


@dataclass(frozen=True, slots=True)
class QuietHours:
    """A daily window when reminders are held back. ``start`` is inclusive, ``end`` exclusive.

    The window may wrap midnight (22:00 to 07:00). Equal start and end mean no quiet hours.
    """

    start: time
    end: time


def _local_moment(day: date, at: time, tz: ZoneInfo) -> datetime:
    """The moment ``at`` on ``day`` in ``tz``.

    A time that does not exist (the hour skipped when clocks go forward) is pushed to the
    same offset-shifted moment instead of raising, e.g. 02:30 becomes 03:30.
    """
    naive = datetime.combine(day, at)
    return naive.replace(tzinfo=tz).astimezone(UTC).astimezone(tz)


def next_daily(after: datetime, time_of_day: time, tz: ZoneInfo) -> datetime:
    """The first moment strictly after ``after`` that is ``time_of_day`` on the user's clock."""
    day = after.astimezone(tz).date()
    candidate = _local_moment(day, time_of_day, tz)
    while candidate <= after:
        day += timedelta(days=1)
        candidate = _local_moment(day, time_of_day, tz)
    return candidate


def next_every_n_days(
    last_done_at: datetime,
    interval_days: int,
    tz: ZoneInfo,
    *,
    time_of_day: time | None = None,
) -> datetime:
    """``interval_days`` local calendar days after the last time it was done.

    The time of day is kept from ``last_done_at`` unless ``time_of_day`` fixes it.
    """
    if interval_days <= 0:
        raise ValueError("interval_days must be positive")
    done_local = last_done_at.astimezone(tz)
    day = done_local.date() + timedelta(days=interval_days)
    return _local_moment(day, time_of_day or done_local.timetz().replace(tzinfo=None), tz)


def after_event(event_at: datetime, delay_minutes: int) -> datetime:
    """A fixed delay after something happened, e.g. 15 minutes after a low reading."""
    if delay_minutes < 0:
        raise ValueError("delay_minutes must not be negative")
    return event_at + timedelta(minutes=delay_minutes)


def in_quiet_hours(moment: datetime, quiet: QuietHours | None, tz: ZoneInfo) -> bool:
    if quiet is None or quiet.start == quiet.end:
        return False
    t = moment.astimezone(tz).time()
    if quiet.start < quiet.end:
        return quiet.start <= t < quiet.end
    return t >= quiet.start or t < quiet.end


def apply_quiet_hours(
    due: datetime, quiet: QuietHours | None, tz: ZoneInfo, *, urgent: bool = False
) -> datetime:
    """Hold a reminder due during quiet hours until they end. Urgent ones are never held."""
    if urgent or quiet is None or not in_quiet_hours(due, quiet, tz):
        return due
    return next_daily(due, quiet.end, tz)


def apply_snooze(due: datetime, snoozed_until: datetime | None) -> datetime:
    """A snooze can delay a reminder but never bring it forward."""
    if snoozed_until is None:
        return due
    return max(due, snoozed_until)
