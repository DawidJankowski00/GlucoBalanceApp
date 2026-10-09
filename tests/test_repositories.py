from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from glucobalance.models import (
    BodySide,
    BodySite,
    BodyView,
    CarbEntry,
    DoseKind,
    GlucoseReading,
    InsulinDose,
    InsulinType,
    Note,
    ReadingSource,
    Reminder,
    ReminderKind,
    SitePurpose,
    SiteRegion,
    SiteUse,
    User,
)
from glucobalance.repositories import (
    CarbRepository,
    GlucoseRepository,
    InsulinRepository,
    NoteRepository,
    ReminderRepository,
    SiteRepository,
    UserRepository,
)

T0 = datetime(2026, 10, 1, 8, 0, tzinfo=UTC)


@pytest.fixture
def user(session: Session) -> User:
    return UserRepository(session).add(User(email="demo@example.com", display_name="Demo"))


def reading(user: User, minutes: int, value: int = 100) -> GlucoseReading:
    return GlucoseReading(
        user=user,
        measured_at=T0 + timedelta(minutes=minutes),
        value_mgdl=value,
        source=ReadingSource.CGM,
    )


def test_user_repository_add_get_and_find_by_email(session: Session, user: User) -> None:
    users = UserRepository(session)
    assert user.id is not None
    assert users.get(user.id) is user
    assert users.get_by_email("demo@example.com") is user
    assert users.get_by_email("nobody@example.com") is None


def test_readings_between_is_ordered_and_half_open(session: Session, user: User) -> None:
    readings = GlucoseRepository(session)
    for minutes in (10, 0, 5, 15):
        readings.add(reading(user, minutes))

    found = readings.between(user.id, T0, T0 + timedelta(minutes=15))
    assert [r.measured_at for r in found] == [T0 + timedelta(minutes=m) for m in (0, 5, 10)]


def test_readings_are_private_to_their_user(session: Session, user: User) -> None:
    other = UserRepository(session).add(User(email="other@example.com", display_name="Other"))
    readings = GlucoseRepository(session)
    readings.add(reading(other, 0))
    assert readings.between(user.id, T0, T0 + timedelta(hours=1)) == []
    assert readings.latest(user.id) is None


def test_latest_reading(session: Session, user: User) -> None:
    readings = GlucoseRepository(session)
    readings.add(reading(user, 0, value=90))
    readings.add(reading(user, 5, value=95))
    latest = readings.latest(user.id)
    assert latest is not None
    assert latest.value_mgdl == 95


def test_add_new_skips_readings_already_stored(session: Session, user: User) -> None:
    readings = GlucoseRepository(session)
    assert readings.add_new([reading(user, 0), reading(user, 5)]) == 2
    # A repeated import overlaps the previous one and repeats a timestamp in the batch.
    assert readings.add_new([reading(user, 5), reading(user, 10), reading(user, 10)]) == 1
    assert len(readings.between(user.id, T0, T0 + timedelta(hours=1))) == 3


def test_add_new_with_nothing_to_add(session: Session) -> None:
    assert GlucoseRepository(session).add_new([]) == 0


def test_naive_datetimes_are_rejected_in_queries(session: Session, user: User) -> None:
    with pytest.raises(ValueError, match="naive"):
        GlucoseRepository(session).between(user.id, datetime(2026, 10, 1), T0)


def test_insulin_carbs_and_notes_between(session: Session, user: User) -> None:
    InsulinRepository(session).add(
        InsulinDose(
            user=user,
            taken_at=T0,
            units=Decimal("3"),
            insulin_type=InsulinType.RAPID,
            kind=DoseKind.BOLUS,
        )
    )
    CarbRepository(session).add(CarbEntry(user=user, eaten_at=T0, grams=Decimal("40")))
    NoteRepository(session).add(Note(user=user, noted_at=T0, text="Run"))

    end = T0 + timedelta(minutes=1)
    assert [d.units for d in InsulinRepository(session).between(user.id, T0, end)] == [3]
    assert [c.grams for c in CarbRepository(session).between(user.id, T0, end)] == [40]
    assert [n.text for n in NoteRepository(session).between(user.id, T0, end)] == ["Run"]


def make_site(code: str) -> BodySite:
    return BodySite(code=code, region=SiteRegion.ABDOMEN, side=BodySide.LEFT, view=BodyView.FRONT)


def test_sites_by_code_and_last_use_per_site(session: Session, user: User) -> None:
    sites = SiteRepository(session)
    a = sites.add(make_site("abdomen-left-1"))
    b = sites.add(make_site("abdomen-left-2"))
    sites.add(make_site("abdomen-left-3"))
    for site, days_ago, purpose in [
        (a, 6, SitePurpose.RAPID_INJECTION),
        (a, 2, SitePurpose.RAPID_INJECTION),
        (b, 4, SitePurpose.RAPID_INJECTION),
        (b, 1, SitePurpose.LONG_INJECTION),
    ]:
        sites.add_use(
            SiteUse(user=user, site=site, used_at=T0 - timedelta(days=days_ago), purpose=purpose)
        )

    assert sites.get_by_code("abdomen-left-2") is b
    assert [s.code for s in sites.all()] == ["abdomen-left-1", "abdomen-left-2", "abdomen-left-3"]
    assert sites.last_used(user.id, SitePurpose.RAPID_INJECTION) == {
        a.id: T0 - timedelta(days=2),
        b.id: T0 - timedelta(days=4),
    }


def test_active_reminders(session: Session, user: User) -> None:
    reminders = ReminderRepository(session)
    reminders.add(Reminder(user=user, kind=ReminderKind.SET_CHANGE, title="Set", interval_days=3))
    reminders.add(Reminder(user=user, kind=ReminderKind.PEN_NEEDLE, title="Needle", active=False))
    assert [r.title for r in reminders.active_for(user.id)] == ["Set"]
