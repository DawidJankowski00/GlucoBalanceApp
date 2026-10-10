"""Glucose statistics: time in range, mean, variability and GMI."""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from glucobalance.models import GlucoseReading, MonitoringMode, ReadingSource
from glucobalance.stats import (
    compute_stats,
    low_episodes,
    time_of_day_averages,
)

T0 = datetime(2026, 10, 1, 0, 0, tzinfo=UTC)


def make(
    values: list[int], *, step_minutes: int = 15, start: datetime = T0
) -> list[GlucoseReading]:
    return [
        GlucoseReading(
            user_id=1,
            measured_at=start + timedelta(minutes=i * step_minutes),
            value_mgdl=value,
            source=ReadingSource.CGM,
        )
        for i, value in enumerate(values)
    ]


def stats(values: list[int], *, days: int = 14, mode: MonitoringMode = MonitoringMode.CGM):  # type: ignore[no-untyped-def]
    return compute_stats(make(values), low=70, high=180, days=days, mode=mode)


def test_no_readings_gives_no_statistics() -> None:
    assert compute_stats([], low=70, high=180, days=14, mode=MonitoringMode.CGM) is None


def test_time_in_range_splits_into_five_bands() -> None:
    # 1 very low, 1 low, 4 in range, 2 high, 1 very high -> 9 readings
    result = stats([50, 65, 100, 120, 150, 180, 200, 240, 260])
    assert result is not None
    assert result.count == 9
    assert result.very_low == pytest.approx(1 / 9 * 100)
    assert result.below == pytest.approx(2 / 9 * 100)  # includes the very low reading
    assert result.in_range == pytest.approx(4 / 9 * 100)  # 180 is still in range
    assert result.above == pytest.approx(3 / 9 * 100)  # includes the very high reading
    assert result.very_high == pytest.approx(1 / 9 * 100)  # above 250
    assert result.below + result.in_range + result.above == pytest.approx(100)


def test_range_edges_belong_to_the_range() -> None:
    result = stats([70, 180])
    assert result is not None
    assert result.in_range == 100


def test_mean_and_variability() -> None:
    result = stats([100, 140])
    assert result is not None
    assert result.mean == 120
    assert result.sd == pytest.approx(28.2843, abs=1e-3)  # sample standard deviation
    assert result.cv == pytest.approx(28.2843 / 120 * 100, abs=1e-2)


def test_one_reading_has_no_spread() -> None:
    result = stats([120])
    assert result is not None
    assert result.sd == 0
    assert result.cv == 0


def test_gmi_formula() -> None:
    result = stats([154] * 10)
    assert result is not None
    assert result.gmi == pytest.approx(3.31 + 0.02392 * 154)


def test_cgm_coverage_counts_fifteen_minute_slots() -> None:
    # 96 readings = one full day of 15-minute slots, over a 1-day period
    result = stats([120] * 96, days=1)
    assert result is not None
    assert result.coverage == pytest.approx(100)


def test_five_minute_readings_do_not_count_coverage_twice() -> None:
    result = compute_stats(
        make([120] * 288, step_minutes=5), low=70, high=180, days=1, mode=MonitoringMode.CGM
    )
    assert result is not None
    assert result.coverage == pytest.approx(100)


def test_short_cgm_period_warns() -> None:
    result = stats([120] * 96, days=7)
    assert result is not None
    assert result.warning is not None
    assert "14 days" in result.warning


def test_low_cgm_coverage_warns() -> None:
    result = stats([120] * 100, days=14)
    assert result is not None
    assert result.coverage is not None and result.coverage < 70
    assert result.warning is not None
    assert "70%" in result.warning


def test_full_cgm_period_has_no_warning() -> None:
    result = stats([120] * (96 * 14), days=14)
    assert result is not None
    assert result.warning is None


def test_glucometer_has_no_coverage_but_warns_when_sparse() -> None:
    result = stats([120] * 10, days=14, mode=MonitoringMode.GLUCOMETER)
    assert result is not None
    assert result.coverage is None
    assert result.warning is not None
    assert "few readings" in result.warning


def test_glucometer_with_enough_readings_has_no_warning() -> None:
    result = stats([120] * 56, days=14, mode=MonitoringMode.GLUCOMETER)
    assert result is not None
    assert result.warning is None


def test_low_episodes_merge_nearby_lows() -> None:
    # a low lasting 45 minutes, a gap of 5 hours, then a second low
    readings = make([100, 60, 55, 65, 100]) + make([100, 62, 100], start=T0 + timedelta(hours=6))
    assert low_episodes(readings, limit=70) == 2


def test_low_episodes_when_never_low() -> None:
    assert low_episodes(make([100, 120]), limit=70) == 0


def test_time_of_day_averages_use_local_time() -> None:
    zone = ZoneInfo("Europe/Warsaw")  # UTC+2 on 1 October 2026
    # 22:00 UTC is midnight local: the night period
    night = make([60], start=datetime(2026, 10, 1, 22, 0, tzinfo=UTC))
    morning = make([100, 140], start=datetime(2026, 10, 2, 5, 0, tzinfo=UTC))  # 07:00 local
    rows = {row.name: row for row in time_of_day_averages([*night, *morning], zone)}
    assert rows["Night"].count == 1
    assert rows["Night"].mean == 60
    assert rows["Morning"].count == 2
    assert rows["Morning"].mean == 120
    assert rows["Evening"].count == 0
    assert rows["Evening"].mean is None
