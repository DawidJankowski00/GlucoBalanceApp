"""One day's readings, doses, carbs and notes merged into a single timeline."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from glucobalance.accounts import register
from glucobalance.models import (
    CarbEntry,
    DoseKind,
    GlucoseReading,
    InsulinDose,
    InsulinType,
    Note,
    ReadingSource,
    User,
)
from glucobalance.timeline import EntryKind, build_timeline, day_bounds, load_day

WARSAW = ZoneInfo("Europe/Warsaw")
T0 = datetime(2026, 10, 9, 6, 0, tzinfo=UTC)  # 08:00 in Warsaw


def at(minutes: int) -> datetime:
    return T0 + timedelta(minutes=minutes)


def reading(user: User, minutes: int, value: int = 120) -> GlucoseReading:
    return GlucoseReading(
        user=user, measured_at=at(minutes), value_mgdl=value, source=ReadingSource.MANUAL
    )


def bolus(user: User, minutes: int) -> InsulinDose:
    return InsulinDose(
        user=user,
        taken_at=at(minutes),
        units=Decimal("4"),
        insulin_type=InsulinType.RAPID,
        kind=DoseKind.BOLUS,
    )


def meal(user: User, minutes: int) -> CarbEntry:
    return CarbEntry(user=user, eaten_at=at(minutes), grams=Decimal("45"))


def note(user: User, minutes: int) -> Note:
    return Note(user=user, noted_at=at(minutes), text="walk")


def test_entries_are_merged_in_time_order(session: Session) -> None:
    user = User(email="a@example.com", display_name="A")
    items = build_timeline(
        readings=[reading(user, 0), reading(user, 120)],
        doses=[bolus(user, 10)],
        carbs=[meal(user, 15)],
        notes=[note(user, 60)],
    )
    assert [(i.at, i.kind) for i in items] == [
        (at(0), EntryKind.GLUCOSE),
        (at(10), EntryKind.INSULIN),
        (at(15), EntryKind.CARBS),
        (at(60), EntryKind.NOTE),
        (at(120), EntryKind.GLUCOSE),
    ]


def test_same_moment_lists_glucose_then_carbs_then_insulin() -> None:
    user = User(email="a@example.com", display_name="A")
    items = build_timeline(
        readings=[reading(user, 0)], doses=[bolus(user, 0)], carbs=[meal(user, 0)], notes=[]
    )
    assert [i.kind for i in items] == [EntryKind.GLUCOSE, EntryKind.CARBS, EntryKind.INSULIN]


def test_each_item_keeps_its_entry() -> None:
    user = User(email="a@example.com", display_name="A")
    dose = bolus(user, 5)
    (item,) = build_timeline(readings=[], doses=[dose], carbs=[], notes=[])
    assert item.entry is dose


def test_an_empty_day_is_an_empty_timeline() -> None:
    assert build_timeline(readings=[], doses=[], carbs=[], notes=[]) == []


def test_day_bounds_are_local_midnights_in_utc() -> None:
    start, end = day_bounds(date(2026, 10, 9), WARSAW)
    assert start == datetime(2026, 10, 8, 22, 0, tzinfo=UTC)
    assert end == datetime(2026, 10, 9, 22, 0, tzinfo=UTC)


def test_the_autumn_clock_change_makes_a_25_hour_day() -> None:
    start, end = day_bounds(date(2026, 10, 25), WARSAW)
    assert end - start == timedelta(hours=25)


def test_the_spring_clock_change_makes_a_23_hour_day() -> None:
    start, end = day_bounds(date(2026, 3, 29), WARSAW)
    assert end - start == timedelta(hours=23)


def test_load_day_reads_only_that_users_local_day(session: Session) -> None:
    ann = register(session, "ann@example.com", "Ann", "correct horse battery")
    bob = register(session, "bob@example.com", "Bob", "correct horse battery")
    start, end = day_bounds(date(2026, 10, 9), WARSAW)
    session.add_all(
        [
            GlucoseReading(
                user=ann, measured_at=start, value_mgdl=100, source=ReadingSource.MANUAL
            ),
            GlucoseReading(
                user=ann,
                measured_at=start - timedelta(minutes=1),
                value_mgdl=101,
                source=ReadingSource.MANUAL,
            ),
            GlucoseReading(user=ann, measured_at=end, value_mgdl=102, source=ReadingSource.MANUAL),
            bolus(ann, 0),
            meal(ann, 0),
            note(ann, 0),
            bolus(bob, 0),
        ]
    )
    session.flush()

    items = load_day(session, ann.id, date(2026, 10, 9), WARSAW)
    assert [i.kind for i in items] == [
        EntryKind.GLUCOSE,
        EntryKind.CARBS,
        EntryKind.INSULIN,
        EntryKind.NOTE,
    ]
    assert items[0].entry.value_mgdl == 100  # type: ignore[union-attr]
