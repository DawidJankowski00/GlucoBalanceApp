"""The hypo log: what was taken to treat a low, linked to the reading and the carbs."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from glucobalance.accounts import register
from glucobalance.entries import EntryError, PossibleDuplicate
from glucobalance.hypo_service import HypoInput, log_hypo, recent_hypos
from glucobalance.models import (
    CarbEntry,
    GlucoseReading,
    HypoTreatment,
    HypoTreatmentKind,
    ReadingSource,
    User,
)

NOW = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)


@pytest.fixture
def user(session: Session) -> User:
    return register(session, "ann@example.com", "Ann", "correct horse battery")


def treatment(
    kind: HypoTreatmentKind = HypoTreatmentKind.JUICE,
    grams: str | None = "15",
    minutes_ago: float = 0,
    **extra: object,
) -> HypoInput:
    return HypoInput(
        treatment=kind,
        treated_at=NOW - timedelta(minutes=minutes_ago),
        carbs_grams=Decimal(grams) if grams is not None else None,
        **extra,  # type: ignore[arg-type]
    )


def reading(user: User, minutes_ago: float, value: int = 58) -> GlucoseReading:
    return GlucoseReading(
        user=user,
        measured_at=NOW - timedelta(minutes=minutes_ago),
        value_mgdl=value,
        source=ReadingSource.MANUAL,
    )


# ---------- saving ----------


def test_a_treatment_with_carbs_also_adds_a_carb_entry(session: Session, user: User) -> None:
    saved = log_hypo(session, user, treatment(note=" shaky "), now=NOW)
    assert saved.id is not None
    assert (saved.treatment, saved.carbs_grams, saved.treated_at) == (
        HypoTreatmentKind.JUICE,
        Decimal("15.0"),
        NOW,
    )
    assert saved.note == "shaky"
    (carbs,) = session.query(CarbEntry).all()
    assert (carbs.grams, carbs.eaten_at, carbs.description) == (
        Decimal("15.0"),
        NOW,
        "Hypo treatment: juice",
    )


def test_glucagon_has_no_carbs(session: Session, user: User) -> None:
    saved = log_hypo(session, user, treatment(HypoTreatmentKind.GLUCAGON, None), now=NOW)
    assert saved.carbs_grams is None
    assert session.query(CarbEntry).count() == 0
    with pytest.raises(EntryError, match="Glucagon has no carbs"):
        log_hypo(
            session,
            user,
            treatment(HypoTreatmentKind.GLUCAGON, "15", minutes_ago=30),
            now=NOW,
        )


def test_carbs_are_optional_for_other_treatments(session: Session, user: User) -> None:
    saved = log_hypo(session, user, treatment(HypoTreatmentKind.FOOD, None), now=NOW)
    assert saved.carbs_grams is None
    assert session.query(CarbEntry).count() == 0


@pytest.mark.parametrize("grams", ["0", "-5", "100.5"])
def test_carbs_must_be_between_1_and_100_grams(session: Session, user: User, grams: str) -> None:
    with pytest.raises(EntryError, match="between 1 and 100 g"):
        log_hypo(session, user, treatment(grams=grams), now=NOW)
    assert session.query(HypoTreatment).count() == 0


def test_time_rules_match_the_other_entries(session: Session, user: User) -> None:
    with pytest.raises(EntryError, match="future"):
        log_hypo(session, user, treatment(minutes_ago=-6), now=NOW)
    with pytest.raises(EntryError, match="30 days"):
        log_hypo(session, user, treatment(minutes_ago=30 * 24 * 60 + 1), now=NOW)


def test_notes_are_trimmed_limited_and_optional(session: Session, user: User) -> None:
    assert log_hypo(session, user, treatment(note="  "), now=NOW).note is None
    with pytest.raises(EntryError, match="500 characters"):
        log_hypo(session, user, treatment(minutes_ago=60, note="x" * 501), now=NOW)


def test_a_rejected_treatment_leaves_nothing_behind(session: Session, user: User) -> None:
    with pytest.raises(EntryError):
        log_hypo(session, user, treatment(note="x" * 501), now=NOW)
    assert session.query(HypoTreatment).count() == 0
    assert session.query(CarbEntry).count() == 0


# ---------- linking to the reading ----------


def test_the_latest_reading_in_the_half_hour_before_is_linked(session: Session, user: User) -> None:
    session.add_all([reading(user, 25, 60), reading(user, 10, 55), reading(user, -5, 120)])
    session.flush()
    saved = log_hypo(session, user, treatment(), now=NOW)
    assert saved.reading is not None
    assert saved.reading.value_mgdl == 55


def test_older_readings_and_other_users_readings_are_not_linked(
    session: Session, user: User
) -> None:
    other = register(session, "bob@example.com", "Bob", "correct horse battery")
    session.add_all([reading(user, 31), reading(other, 5)])
    session.flush()
    assert log_hypo(session, user, treatment(), now=NOW).reading is None


# ---------- duplicates ----------


def test_the_same_treatment_within_ten_minutes_needs_confirming(
    session: Session, user: User
) -> None:
    log_hypo(session, user, treatment(minutes_ago=8), now=NOW)
    with pytest.raises(PossibleDuplicate, match="already logged juice"):
        log_hypo(session, user, treatment(), now=NOW)
    log_hypo(session, user, treatment(confirmed=True), now=NOW)
    assert session.query(HypoTreatment).count() == 2


def test_a_different_treatment_or_a_later_one_is_not_a_duplicate(
    session: Session, user: User
) -> None:
    log_hypo(session, user, treatment(minutes_ago=11), now=NOW)
    log_hypo(session, user, treatment(), now=NOW)
    log_hypo(session, user, treatment(HypoTreatmentKind.SWEETS, "10", minutes_ago=2), now=NOW)


# ---------- listing ----------


def test_recent_treatments_are_newest_first_and_limited(session: Session, user: User) -> None:
    other = register(session, "bob@example.com", "Bob", "correct horse battery")
    for minutes_ago in (120, 20, 60):
        log_hypo(session, user, treatment(minutes_ago=minutes_ago), now=NOW)
    log_hypo(session, other, treatment(), now=NOW)
    assert [t.treated_at for t in recent_hypos(session, user, limit=2)] == [
        NOW - timedelta(minutes=20),
        NOW - timedelta(minutes=60),
    ]
