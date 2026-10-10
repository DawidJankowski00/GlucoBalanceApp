"""Tests for the insulin-on-board model (linear decay over the insulin action time)."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from glucobalance.iob import insulin_on_board
from glucobalance.models import DoseKind, InsulinDose, InsulinType

NOW = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)
ACTION = 240  # minutes


def dose(
    minutes_ago: int,
    units: str,
    *,
    insulin_type: InsulinType = InsulinType.RAPID,
    kind: DoseKind = DoseKind.BOLUS,
) -> InsulinDose:
    return InsulinDose(
        user_id=1,
        taken_at=NOW - timedelta(minutes=minutes_ago),
        units=Decimal(units),
        insulin_type=insulin_type,
        kind=kind,
    )


def test_no_doses_means_no_insulin_on_board() -> None:
    assert insulin_on_board([], NOW, ACTION) == Decimal("0")


def test_a_dose_taken_just_now_counts_in_full() -> None:
    assert insulin_on_board([dose(0, "4")], NOW, ACTION) == Decimal("4")


def test_a_dose_halfway_through_its_action_time_counts_half() -> None:
    assert insulin_on_board([dose(120, "4")], NOW, ACTION) == Decimal("2")


def test_a_dose_at_exactly_the_action_time_counts_nothing() -> None:
    assert insulin_on_board([dose(240, "4")], NOW, ACTION) == Decimal("0")


def test_an_old_dose_counts_nothing() -> None:
    assert insulin_on_board([dose(600, "4")], NOW, ACTION) == Decimal("0")


def test_doses_are_added_together() -> None:
    doses = [dose(60, "4"), dose(180, "2")]  # 4 * 0.75 + 2 * 0.25
    assert insulin_on_board(doses, NOW, ACTION) == Decimal("3.5")


def test_a_future_dose_is_ignored() -> None:
    assert insulin_on_board([dose(-30, "4")], NOW, ACTION) == Decimal("0")


def test_long_acting_and_basal_doses_are_ignored() -> None:
    doses = [
        dose(30, "20", insulin_type=InsulinType.LONG, kind=DoseKind.BASAL),
        dose(30, "1", kind=DoseKind.BASAL),
    ]
    assert insulin_on_board(doses, NOW, ACTION) == Decimal("0")


def test_corrections_count_like_boluses() -> None:
    assert insulin_on_board([dose(120, "2", kind=DoseKind.CORRECTION)], NOW, ACTION) == Decimal("1")


def test_a_longer_action_time_keeps_insulin_on_board_longer() -> None:
    assert insulin_on_board([dose(120, "4")], NOW, 360) > insulin_on_board(
        [dose(120, "4")], NOW, 240
    )
