"""advise_bolus: data from the database, the safety rules first, then the calculator."""

from dataclasses import replace
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from glucobalance.accounts import register
from glucobalance.dosing_safety import Refusal, RefusalReason
from glucobalance.dosing_service import BolusAdvice, advise_bolus, correction_target
from glucobalance.models import (
    ChangeSource,
    DoseKind,
    GlucoseReading,
    InsulinDose,
    InsulinType,
    ReadingSource,
    User,
)
from glucobalance.settings_service import TimeBlockInput, apply_settings
from test_settings_service import make_input

NOW = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)  # 14:00 in Warsaw


@pytest.fixture
def user(session: Session) -> User:
    """Target 70 to 180 (correction target 125), ICR 10 and ISF 40 from 00:00, 15 g/U and
    ISF 50 from 13:00 local, a 10-unit max bolus and a 0.5-unit step."""
    user = register(session, "ann@example.com", "Ann", "correct horse battery")
    data = replace(
        make_input(),
        timezone="Europe/Warsaw",
        time_blocks=(
            TimeBlockInput(time(0, 0), Decimal("10"), 40),
            TimeBlockInput(time(13, 0), Decimal("15"), 50),
        ),
    )
    apply_settings(session, user, data, ChangeSource.ONBOARDING, user)
    return user


def add_reading(session: Session, user: User, value: int, minutes_ago: int = 5) -> None:
    session.add(
        GlucoseReading(
            user_id=user.id,
            measured_at=NOW - timedelta(minutes=minutes_ago),
            value_mgdl=value,
            source=ReadingSource.CGM,
        )
    )
    session.flush()


def advice(session: Session, user: User, carbs: str) -> BolusAdvice:
    result = advise_bolus(session, user, Decimal(carbs), now=NOW)
    assert isinstance(result, BolusAdvice)
    return result


def refusal(session: Session, user: User, carbs: str = "30") -> RefusalReason:
    result = advise_bolus(session, user, Decimal(carbs), now=NOW)
    assert isinstance(result, Refusal)
    return result.reason


def test_correction_target_is_the_middle_of_the_range() -> None:
    assert correction_target(70, 180) == 125


def test_uses_the_block_for_the_local_time(session: Session, user: User) -> None:
    add_reading(session, user, 125)
    result = advice(session, user, "45")
    assert result.block_start == time(13, 0)
    assert result.result.units == Decimal("3")


def test_adds_a_correction_above_the_target(session: Session, user: User) -> None:
    add_reading(session, user, 225)  # (225 - 125) / 50 = 2
    assert advice(session, user, "45").result.units == Decimal("5")


def test_takes_off_insulin_on_board(session: Session, user: User) -> None:
    add_reading(session, user, 125)
    session.add(
        InsulinDose(
            user_id=user.id,
            taken_at=NOW - timedelta(minutes=120),
            units=Decimal("2"),
            insulin_type=InsulinType.RAPID,
            kind=DoseKind.BOLUS,
        )
    )
    session.flush()
    result = advice(session, user, "45")  # 3 - 1
    assert result.result.iob_units == Decimal("1")
    assert result.result.units == Decimal("2")


def test_caps_at_the_max_bolus(session: Session, user: User) -> None:
    add_reading(session, user, 125)
    result = advice(session, user, "300")
    assert result.result.units == Decimal("10")
    assert result.result.capped


def test_refuses_without_settings(session: Session) -> None:
    other = register(session, "bob@example.com", "Bob", "correct horse battery")
    assert refusal(session, other) is RefusalReason.NO_SETTINGS


def test_refuses_without_a_reading(session: Session, user: User) -> None:
    assert refusal(session, user) is RefusalReason.NO_READING


def test_refuses_a_stale_reading(session: Session, user: User) -> None:
    add_reading(session, user, 150, minutes_ago=45)
    assert refusal(session, user) is RefusalReason.STALE_READING


def test_refuses_a_low(session: Session, user: User) -> None:
    add_reading(session, user, 62)
    assert refusal(session, user) is RefusalReason.LOW_GLUCOSE


@pytest.mark.parametrize("carbs", ["-1", "301"])
def test_rejects_carbs_out_of_range(session: Session, user: User, carbs: str) -> None:
    add_reading(session, user, 125)
    with pytest.raises(ValueError, match="carbs"):
        advise_bolus(session, user, Decimal(carbs), now=NOW)
