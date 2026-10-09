"""The simulator source: a replayed glucose trace that behaves like a live CGM."""

from datetime import UTC, datetime, timedelta

import pytest

from glucobalance.cgm.base import CGMReading, trend_from_rate
from glucobalance.cgm.simulator import (
    MAX_HISTORY,
    STEP,
    SimulatorSource,
    demo_trace,
)
from glucobalance.models import Trend

NOW = datetime(2026, 10, 9, 12, 2, tzinfo=UTC)


def source(trace: list[int], now: datetime = NOW) -> SimulatorSource:
    return SimulatorSource(trace, clock=lambda: now)


@pytest.mark.parametrize(
    ("rate", "expected"),
    [
        (-3.0, Trend.FALLING_FAST),
        (-1.5, Trend.FALLING),
        (0.0, Trend.STEADY),
        (1.0, Trend.STEADY),
        (1.5, Trend.RISING),
        (2.5, Trend.RISING_FAST),
    ],
)
def test_trend_from_rate_uses_the_cgm_arrow_bands(rate: float, expected: Trend) -> None:
    assert trend_from_rate(rate) is expected


def test_readings_sit_on_a_five_minute_grid_and_stop_at_now() -> None:
    readings = source([100, 110, 120]).fetch_readings(NOW - timedelta(minutes=16))

    assert [r.measured_at for r in readings] == [
        datetime(2026, 10, 9, 11, 50, tzinfo=UTC),
        datetime(2026, 10, 9, 11, 55, tzinfo=UTC),
        datetime(2026, 10, 9, 12, 0, tzinfo=UTC),
    ]
    assert all(r.measured_at.minute % 5 == 0 for r in readings)


def test_since_is_exclusive() -> None:
    readings = source([100]).fetch_readings(datetime(2026, 10, 9, 11, 55, tzinfo=UTC))

    assert [r.measured_at for r in readings] == [datetime(2026, 10, 9, 12, 0, tzinfo=UTC)]


def test_the_same_moment_always_gives_the_same_value() -> None:
    trace = [90, 140, 200, 75]
    first = source(trace).fetch_readings(NOW - timedelta(hours=1))
    later = source(trace, NOW + timedelta(minutes=30)).fetch_readings(NOW - timedelta(hours=1))

    assert later[: len(first)] == first


def test_the_trace_repeats_and_trend_follows_the_change() -> None:
    readings = source([100, 120]).fetch_readings(NOW - timedelta(minutes=11))

    values = [r.value_mgdl for r in readings]
    assert values[0] != values[1]  # alternates between the two values
    rising = next(r for r in readings if r.value_mgdl == 120)
    falling = next(r for r in readings if r.value_mgdl == 100)
    assert rising.trend is Trend.RISING_FAST  # +20 in 5 minutes = +4 per minute
    assert falling.trend is Trend.FALLING_FAST


def test_history_is_capped() -> None:
    readings = source([100]).fetch_readings(NOW - timedelta(days=10))

    assert readings[0].measured_at >= NOW - MAX_HISTORY
    assert len(readings) == MAX_HISTORY // STEP


def test_nothing_new_returns_an_empty_list() -> None:
    assert source([100]).fetch_readings(NOW) == []


def test_an_empty_trace_is_refused() -> None:
    with pytest.raises(ValueError, match="trace"):
        SimulatorSource([], clock=lambda: NOW)


def test_the_built_in_demo_trace_covers_a_day_in_a_plausible_range() -> None:
    trace = demo_trace()

    assert len(trace) == 24 * 60 // 5
    assert min(trace) >= 55
    assert max(trace) <= 260
    assert trace == demo_trace()  # deterministic


def test_readings_are_cgm_readings() -> None:
    reading = source([100]).fetch_readings(NOW - timedelta(minutes=3))[0]

    assert isinstance(reading, CGMReading)
    assert reading.measured_at.tzinfo is UTC
