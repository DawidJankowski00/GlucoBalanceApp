"""The pure reminder rules: when is a reminder next due, and what quiet hours and snooze do."""

from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from glucobalance.reminder_rules import (
    QuietHours,
    after_event,
    apply_quiet_hours,
    apply_snooze,
    in_quiet_hours,
    next_daily,
    next_every_n_days,
)

WARSAW = ZoneInfo("Europe/Warsaw")
NIGHT = QuietHours(start=time(22, 0), end=time(7, 0))  # wraps midnight
SIESTA = QuietHours(start=time(13, 0), end=time(15, 0))  # same day


def utc(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=UTC)


def local(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=WARSAW)


# ---------- daily at a time ----------


def test_daily_is_today_when_the_time_is_still_ahead() -> None:
    now = local(2026, 10, 9, 8, 0)
    assert next_daily(now, time(20, 0), WARSAW) == local(2026, 10, 9, 20, 0)


def test_daily_is_tomorrow_when_the_time_has_passed() -> None:
    now = local(2026, 10, 9, 21, 0)
    assert next_daily(now, time(20, 0), WARSAW) == local(2026, 10, 10, 20, 0)


def test_daily_at_exactly_now_moves_to_tomorrow() -> None:
    now = local(2026, 10, 9, 20, 0)
    assert next_daily(now, time(20, 0), WARSAW) == local(2026, 10, 10, 20, 0)


def test_daily_uses_the_users_time_zone_not_utc() -> None:
    # 23:30 UTC is already 01:30 on the 10th in Warsaw, so 08:00 is the same local morning.
    now = utc(2026, 10, 9, 23, 30)
    assert next_daily(now, time(8, 0), WARSAW) == local(2026, 10, 10, 8, 0)


def test_daily_keeps_the_local_time_across_a_clock_change() -> None:
    # Clocks go back in Warsaw on 2026-10-25: the day is 25 hours long.
    now = local(2026, 10, 24, 21, 0)
    due = next_daily(now, time(8, 0), WARSAW)
    assert due == local(2026, 10, 25, 8, 0)
    assert due.astimezone(UTC) - now.astimezone(UTC) == timedelta(
        hours=12
    )  # 11 elapsed hours + the extra hour


def test_daily_in_the_missing_hour_still_returns_a_moment_after_now() -> None:
    # 02:30 does not exist in Warsaw on 2026-03-29 (clocks jump 02:00 -> 03:00).
    now = local(2026, 3, 28, 23, 0)
    due = next_daily(now, time(2, 30), WARSAW)
    assert due > now
    assert due.astimezone(WARSAW).date().isoformat() == "2026-03-29"


# ---------- every N days ----------


def test_every_n_days_counts_local_calendar_days_from_the_last_done_time() -> None:
    done = local(2026, 10, 9, 21, 15)
    assert next_every_n_days(done, 3, WARSAW) == local(2026, 10, 12, 21, 15)


def test_every_n_days_can_fix_the_time_of_day() -> None:
    done = local(2026, 10, 9, 21, 15)
    assert next_every_n_days(done, 3, WARSAW, time_of_day=time(8, 0)) == local(2026, 10, 12, 8, 0)


def test_every_n_days_keeps_the_local_time_across_a_clock_change() -> None:
    done = local(2026, 10, 24, 8, 0)
    assert next_every_n_days(done, 2, WARSAW) == local(2026, 10, 26, 8, 0)


def test_every_n_days_rejects_a_non_positive_interval() -> None:
    import pytest

    with pytest.raises(ValueError):
        next_every_n_days(local(2026, 10, 9, 8, 0), 0, WARSAW)


# ---------- after an event ----------


def test_after_event_adds_the_delay() -> None:
    event = utc(2026, 10, 9, 10, 0)
    assert after_event(event, 15) == utc(2026, 10, 9, 10, 15)


def test_after_event_rejects_a_negative_delay() -> None:
    import pytest

    with pytest.raises(ValueError):
        after_event(utc(2026, 10, 9, 10, 0), -1)


# ---------- quiet hours ----------


def test_quiet_hours_that_wrap_midnight() -> None:
    assert in_quiet_hours(local(2026, 10, 9, 23, 0), NIGHT, WARSAW)
    assert in_quiet_hours(local(2026, 10, 10, 6, 59), NIGHT, WARSAW)
    assert not in_quiet_hours(local(2026, 10, 10, 7, 0), NIGHT, WARSAW)  # end is exclusive
    assert in_quiet_hours(local(2026, 10, 9, 22, 0), NIGHT, WARSAW)  # start is inclusive
    assert not in_quiet_hours(local(2026, 10, 9, 12, 0), NIGHT, WARSAW)


def test_quiet_hours_within_one_day() -> None:
    assert in_quiet_hours(local(2026, 10, 9, 14, 0), SIESTA, WARSAW)
    assert not in_quiet_hours(local(2026, 10, 9, 15, 0), SIESTA, WARSAW)


def test_no_quiet_hours_means_never_quiet() -> None:
    assert not in_quiet_hours(local(2026, 10, 9, 3, 0), None, WARSAW)


def test_equal_start_and_end_means_no_quiet_hours() -> None:
    assert not in_quiet_hours(local(2026, 10, 9, 3, 0), QuietHours(time(7, 0), time(7, 0)), WARSAW)


def test_apply_quiet_hours_holds_a_night_reminder_until_morning() -> None:
    assert apply_quiet_hours(local(2026, 10, 9, 23, 30), NIGHT, WARSAW) == local(2026, 10, 10, 7, 0)
    assert apply_quiet_hours(local(2026, 10, 10, 2, 0), NIGHT, WARSAW) == local(2026, 10, 10, 7, 0)


def test_apply_quiet_hours_leaves_a_daytime_reminder_alone() -> None:
    due = local(2026, 10, 9, 12, 0)
    assert apply_quiet_hours(due, NIGHT, WARSAW) == due
    assert apply_quiet_hours(due, None, WARSAW) == due


def test_urgent_reminders_ignore_quiet_hours() -> None:
    due = local(2026, 10, 9, 23, 30)
    assert apply_quiet_hours(due, NIGHT, WARSAW, urgent=True) == due


# ---------- snooze ----------


def test_snooze_pushes_a_due_time_later() -> None:
    due = utc(2026, 10, 9, 10, 0)
    assert apply_snooze(due, utc(2026, 10, 9, 10, 30)) == utc(2026, 10, 9, 10, 30)


def test_an_old_snooze_does_not_pull_a_due_time_earlier() -> None:
    due = utc(2026, 10, 9, 10, 0)
    assert apply_snooze(due, utc(2026, 10, 9, 9, 0)) == due


def test_no_snooze_changes_nothing() -> None:
    due = utc(2026, 10, 9, 10, 0)
    assert apply_snooze(due, None) == due
