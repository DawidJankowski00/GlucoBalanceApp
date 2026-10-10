"""The safety rules that decide whether any dose number may be shown."""

from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta

import pytest

from glucobalance.dosing_safety import STALE_AFTER, RefusalReason, block_at, check_glucose

NOW = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)


@dataclass(frozen=True)
class Reading:
    measured_at: datetime
    value_mgdl: int


@dataclass(frozen=True)
class Block:
    start_time: time


def test_a_fresh_in_range_reading_passes() -> None:
    assert check_glucose(Reading(NOW - timedelta(minutes=5), 140), NOW) is None


def test_no_reading_is_refused() -> None:
    refusal = check_glucose(None, NOW)
    assert refusal is not None
    assert refusal.reason is RefusalReason.NO_READING


def test_a_stale_reading_is_refused() -> None:
    refusal = check_glucose(Reading(NOW - STALE_AFTER - timedelta(seconds=1), 140), NOW)
    assert refusal is not None
    assert refusal.reason is RefusalReason.STALE_READING


def test_a_reading_exactly_at_the_stale_limit_still_passes() -> None:
    assert check_glucose(Reading(NOW - STALE_AFTER, 140), NOW) is None


@pytest.mark.parametrize("value", [40, 54, 69])
def test_a_low_is_refused(value: int) -> None:
    refusal = check_glucose(Reading(NOW, value), NOW)
    assert refusal is not None
    assert refusal.reason is RefusalReason.LOW_GLUCOSE


def test_seventy_is_not_a_low() -> None:
    assert check_glucose(Reading(NOW, 70), NOW) is None


def test_staleness_is_checked_before_the_value() -> None:
    refusal = check_glucose(Reading(NOW - timedelta(hours=2), 50), NOW)
    assert refusal is not None
    assert refusal.reason is RefusalReason.STALE_READING


BLOCKS = [Block(time(11, 0)), Block(time(0, 0)), Block(time(6, 0))]


@pytest.mark.parametrize(
    ("local", "start"),
    [
        (time(0, 0), time(0, 0)),
        (time(5, 59), time(0, 0)),
        (time(6, 0), time(6, 0)),
        (time(10, 30), time(6, 0)),
        (time(23, 59), time(11, 0)),
    ],
)
def test_block_at_picks_the_block_in_force(local: time, start: time) -> None:
    block = block_at(BLOCKS, local)
    assert block is not None
    assert block.start_time == start


def test_block_at_with_no_blocks() -> None:
    assert block_at(list[Block](), time(8, 0)) is None
