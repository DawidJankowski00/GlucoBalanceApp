"""Rules for logging a glucose reading by hand: range, time and duplicate checks."""

from datetime import UTC, datetime, time, timedelta

import pytest
from sqlalchemy.orm import Session

from glucobalance.accounts import register
from glucobalance.glucose_service import (
    GlucoseEntry,
    GlucoseEntryError,
    is_low,
    log_reading,
    recent_readings,
    suggest_tag,
)
from glucobalance.models import GlucoseReading, GlucoseTag, ReadingSource, User

NOW = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)


@pytest.fixture
def user(session: Session) -> User:
    return register(session, "ann@example.com", "Ann", "correct horse battery")


def entry(value: int = 110, minutes_ago: float = 0, **extra: object) -> GlucoseEntry:
    return GlucoseEntry(
        value_mgdl=value,
        measured_at=NOW - timedelta(minutes=minutes_ago),
        **extra,  # type: ignore[arg-type]
    )


# ---------- saving ----------


def test_a_valid_reading_is_saved_as_manual(session: Session, user: User) -> None:
    reading = log_reading(
        session, user, entry(126, tag=GlucoseTag.BEFORE_MEAL, note="after a walk"), now=NOW
    )
    assert reading.id is not None
    assert reading.user_id == user.id
    assert reading.value_mgdl == 126
    assert reading.measured_at == NOW
    assert reading.source is ReadingSource.MANUAL
    assert reading.tag is GlucoseTag.BEFORE_MEAL
    assert reading.note == "after a walk"


def test_blank_note_is_stored_as_none(session: Session, user: User) -> None:
    assert log_reading(session, user, entry(note="   "), now=NOW).note is None


def test_note_is_trimmed_and_limited(session: Session, user: User) -> None:
    assert log_reading(session, user, entry(note="  ok  "), now=NOW).note == "ok"
    with pytest.raises(GlucoseEntryError, match="500 characters"):
        log_reading(session, user, entry(minutes_ago=30, note="x" * 501), now=NOW)


# ---------- plausible range ----------


@pytest.mark.parametrize("value", [20, 39, 400, 600])
def test_values_a_meter_can_show_are_accepted(session: Session, user: User, value: int) -> None:
    assert log_reading(session, user, entry(value), now=NOW).value_mgdl == value


@pytest.mark.parametrize("value", [0, 19, 601, 1000])
def test_implausible_values_are_rejected(session: Session, user: User, value: int) -> None:
    with pytest.raises(GlucoseEntryError, match="between 20 and 600 mg/dL"):
        log_reading(session, user, entry(value), now=NOW)


# ---------- time ----------


def test_a_few_minutes_in_the_future_is_allowed_for_clock_drift(
    session: Session, user: User
) -> None:
    log_reading(session, user, entry(minutes_ago=-5), now=NOW)


def test_further_in_the_future_is_rejected(session: Session, user: User) -> None:
    with pytest.raises(GlucoseEntryError, match="future"):
        log_reading(session, user, entry(minutes_ago=-6), now=NOW)


def test_up_to_30_days_back_is_allowed(session: Session, user: User) -> None:
    log_reading(session, user, entry(minutes_ago=30 * 24 * 60), now=NOW)


def test_older_than_30_days_is_rejected(session: Session, user: User) -> None:
    with pytest.raises(GlucoseEntryError, match="30 days"):
        log_reading(session, user, entry(minutes_ago=30 * 24 * 60 + 1), now=NOW)


def test_naive_time_is_rejected(session: Session, user: User) -> None:
    naive = GlucoseEntry(value_mgdl=100, measured_at=datetime(2026, 10, 9, 12, 0))
    with pytest.raises(ValueError, match="timezone"):
        log_reading(session, user, naive, now=NOW)


# ---------- duplicates ----------


def test_second_reading_in_the_same_minute_is_rejected(session: Session, user: User) -> None:
    log_reading(session, user, entry(110), now=NOW)
    later_same_minute = GlucoseEntry(value_mgdl=150, measured_at=NOW + timedelta(seconds=40))
    with pytest.raises(GlucoseEntryError, match="already logged a reading at"):
        log_reading(session, user, later_same_minute, now=NOW)


def test_same_value_within_five_minutes_is_a_double_tap(session: Session, user: User) -> None:
    log_reading(session, user, entry(110, minutes_ago=4), now=NOW)
    with pytest.raises(GlucoseEntryError, match="same value"):
        log_reading(session, user, entry(110), now=NOW)


def test_same_value_more_than_five_minutes_apart_is_fine(session: Session, user: User) -> None:
    log_reading(session, user, entry(110, minutes_ago=6), now=NOW)
    log_reading(session, user, entry(110), now=NOW)


def test_different_value_a_minute_later_is_fine(session: Session, user: User) -> None:
    log_reading(session, user, entry(110, minutes_ago=1), now=NOW)
    log_reading(session, user, entry(115), now=NOW)


def test_cgm_readings_do_not_count_as_duplicates(session: Session, user: User) -> None:
    session.add(
        GlucoseReading(
            user=user, measured_at=NOW, value_mgdl=110, source=ReadingSource.CGM, tag=None
        )
    )
    session.flush()
    log_reading(session, user, entry(110), now=NOW)


def test_other_users_readings_do_not_count(session: Session, user: User) -> None:
    other = register(session, "bob@example.com", "Bob", "correct horse battery")
    log_reading(session, other, entry(110), now=NOW)
    log_reading(session, user, entry(110), now=NOW)


def test_a_rejected_reading_is_not_saved(session: Session, user: User) -> None:
    with pytest.raises(GlucoseEntryError):
        log_reading(session, user, entry(5), now=NOW)
    assert session.query(GlucoseReading).count() == 0


# ---------- helpers ----------


def test_recent_readings_are_newest_first_and_limited(session: Session, user: User) -> None:
    for minutes_ago, value in [(60, 100), (30, 110), (10, 120), (20, 130)]:
        log_reading(session, user, entry(value, minutes_ago=minutes_ago), now=NOW)
    assert [r.value_mgdl for r in recent_readings(session, user, limit=3)] == [120, 130, 110]


@pytest.mark.parametrize(
    ("local", "tag"),
    [
        (time(5, 0), GlucoseTag.FASTING),
        (time(8, 59), GlucoseTag.FASTING),
        (time(9, 0), None),
        (time(13, 0), None),
        (time(21, 59), None),
        (time(22, 0), GlucoseTag.BEDTIME),
        (time(1, 59), GlucoseTag.BEDTIME),
        (time(2, 0), GlucoseTag.NIGHT),
        (time(4, 59), GlucoseTag.NIGHT),
    ],
)
def test_tag_is_suggested_from_the_local_time(local: time, tag: GlucoseTag | None) -> None:
    assert suggest_tag(local) is tag


@pytest.mark.parametrize(("value", "low"), [(54, True), (69, True), (70, False), (180, False)])
def test_low_means_below_70(value: int, low: bool) -> None:
    assert is_low(value) is low
