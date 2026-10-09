"""Rules for logging insulin doses and carbs by hand (treatment_service)."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from glucobalance.accounts import register
from glucobalance.entries import EntryError, PossibleDuplicate
from glucobalance.models import (
    CarbEntry,
    ChangeSource,
    DeliveryMode,
    DoseKind,
    InsulinDose,
    InsulinType,
    User,
)
from glucobalance.settings_service import apply_settings
from glucobalance.treatment_service import (
    CarbInput,
    DoseInput,
    log_carbs,
    log_dose,
)
from test_settings_service import make_input

NOW = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)


@pytest.fixture
def user(session: Session) -> User:
    """A pen user with a 10-unit maximum bolus and a 0.5-unit dose step."""
    user = register(session, "ann@example.com", "Ann", "correct horse battery")
    pens = replace(make_input(), delivery_mode=DeliveryMode.PENS)
    apply_settings(session, user, pens, ChangeSource.ONBOARDING, user)
    return user


def dose(
    units: str = "4",
    kind: DoseKind = DoseKind.BOLUS,
    insulin: InsulinType = InsulinType.RAPID,
    minutes_ago: float = 0,
    confirmed: bool = False,
) -> DoseInput:
    return DoseInput(
        units=Decimal(units),
        insulin_type=insulin,
        kind=kind,
        taken_at=NOW - timedelta(minutes=minutes_ago),
        confirmed=confirmed,
    )


def carbs(
    grams: str = "45", minutes_ago: float = 0, description: str | None = None, **kw: bool
) -> CarbInput:
    return CarbInput(
        grams=Decimal(grams),
        eaten_at=NOW - timedelta(minutes=minutes_ago),
        description=description,
        **kw,
    )


# ---------- insulin ----------


def test_a_valid_bolus_is_saved(session: Session, user: User) -> None:
    saved = log_dose(session, user, dose("4.5"), now=NOW)
    assert saved.id is not None
    assert (saved.units, saved.kind, saved.insulin_type) == (
        Decimal("4.5"),
        DoseKind.BOLUS,
        InsulinType.RAPID,
    )
    assert saved.taken_at == NOW


@pytest.mark.parametrize("units", ["0", "-1"])
def test_units_must_be_positive(session: Session, user: User, units: str) -> None:
    with pytest.raises(EntryError, match="more than 0"):
        log_dose(session, user, dose(units), now=NOW)


def test_units_must_match_the_dose_step(session: Session, user: User) -> None:
    with pytest.raises(EntryError, match="steps of 0.5"):
        log_dose(session, user, dose("4.3"), now=NOW)


@pytest.mark.parametrize("kind", [DoseKind.BOLUS, DoseKind.CORRECTION])
def test_bolus_and_correction_are_capped_by_the_max_bolus(
    session: Session, user: User, kind: DoseKind
) -> None:
    log_dose(session, user, dose("10", kind=kind), now=NOW)
    with pytest.raises(EntryError, match="maximum bolus of 10 units"):
        log_dose(session, user, dose("10.5", kind=kind, minutes_ago=30), now=NOW)


def test_long_acting_basal_may_exceed_the_max_bolus(session: Session, user: User) -> None:
    log_dose(session, user, dose("22", kind=DoseKind.BASAL, insulin=InsulinType.LONG), now=NOW)


def test_basal_is_capped_at_100_units(session: Session, user: User) -> None:
    with pytest.raises(EntryError, match="100 units"):
        log_dose(
            session, user, dose("100.5", kind=DoseKind.BASAL, insulin=InsulinType.LONG), now=NOW
        )


def test_bolus_with_long_acting_insulin_is_rejected(session: Session, user: User) -> None:
    with pytest.raises(EntryError, match="rapid-acting"):
        log_dose(session, user, dose(insulin=InsulinType.LONG), now=NOW)


def test_dose_time_follows_the_same_rules_as_readings(session: Session, user: User) -> None:
    with pytest.raises(EntryError, match="future"):
        log_dose(session, user, dose(minutes_ago=-6), now=NOW)
    with pytest.raises(EntryError, match="30 days"):
        log_dose(session, user, dose(minutes_ago=30 * 24 * 60 + 1), now=NOW)


def test_same_dose_within_ten_minutes_needs_confirming(session: Session, user: User) -> None:
    log_dose(session, user, dose("4", minutes_ago=8), now=NOW)
    with pytest.raises(PossibleDuplicate, match="already logged 4 units"):
        log_dose(session, user, dose("4"), now=NOW)
    assert session.query(InsulinDose).count() == 1

    log_dose(session, user, dose("4", confirmed=True), now=NOW)
    assert session.query(InsulinDose).count() == 2


def test_different_dose_or_kind_is_not_a_duplicate(session: Session, user: User) -> None:
    log_dose(session, user, dose("4", minutes_ago=2), now=NOW)
    log_dose(session, user, dose("4.5"), now=NOW)
    log_dose(session, user, dose("4", kind=DoseKind.CORRECTION), now=NOW)


def test_same_dose_after_ten_minutes_is_fine(session: Session, user: User) -> None:
    log_dose(session, user, dose("4", minutes_ago=11), now=NOW)
    log_dose(session, user, dose("4"), now=NOW)


def test_possible_duplicate_is_an_entry_error() -> None:
    assert issubclass(PossibleDuplicate, EntryError)


# ---------- carbs ----------


def test_valid_carbs_are_saved(session: Session, user: User) -> None:
    saved = log_carbs(session, user, carbs("42.5", description=" porridge "), now=NOW)
    assert (saved.grams, saved.description, saved.eaten_at) == (Decimal("42.5"), "porridge", NOW)


@pytest.mark.parametrize("grams", ["0", "0.5", "300.5", "1000"])
def test_carbs_must_be_between_1_and_300_grams(session: Session, user: User, grams: str) -> None:
    with pytest.raises(EntryError, match="between 1 and 300 g"):
        log_carbs(session, user, carbs(grams), now=NOW)


def test_carbs_are_rounded_to_a_tenth(session: Session, user: User) -> None:
    assert log_carbs(session, user, carbs("12.34"), now=NOW).grams == Decimal("12.3")


def test_carb_description_is_limited(session: Session, user: User) -> None:
    with pytest.raises(EntryError, match="200 characters"):
        log_carbs(session, user, carbs(description="x" * 201), now=NOW)


def test_same_carbs_within_ten_minutes_need_confirming(session: Session, user: User) -> None:
    log_carbs(session, user, carbs("45", minutes_ago=5), now=NOW)
    with pytest.raises(PossibleDuplicate, match="already logged 45 g"):
        log_carbs(session, user, carbs("45"), now=NOW)
    log_carbs(session, user, carbs("45", confirmed=True), now=NOW)
    assert session.query(CarbEntry).count() == 2
