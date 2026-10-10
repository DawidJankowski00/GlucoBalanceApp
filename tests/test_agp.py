"""The ambulatory glucose profile: percentile bands over a typical day."""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from glucobalance.agp import agp_figure, agp_profile, percentile
from glucobalance.models import DisplayUnit, GlucoseReading, ReadingSource

WARSAW = ZoneInfo("Europe/Warsaw")  # UTC+2 in October 2026


def reading(day: int, hour: int, minute: int, value: int) -> GlucoseReading:
    """A reading at local time ``hour:minute`` on October ``day`` 2026 (Warsaw)."""
    local = datetime(2026, 10, day, hour, minute, tzinfo=WARSAW)
    return GlucoseReading(
        user_id=1, measured_at=local.astimezone(UTC), value_mgdl=value, source=ReadingSource.CGM
    )


def test_percentile_interpolates_between_values() -> None:
    values = [10.0, 20.0, 30.0, 40.0, 50.0]
    assert percentile(values, 0) == 10
    assert percentile(values, 50) == 30
    assert percentile(values, 100) == 50
    assert percentile(values, 25) == 20
    assert percentile(values, 10) == pytest.approx(14)


def test_percentile_of_one_value() -> None:
    assert percentile([7.0], 95) == 7


def test_percentile_of_nothing_is_an_error() -> None:
    with pytest.raises(ValueError, match="no values"):
        percentile([], 50)


def test_days_are_folded_onto_one_clock() -> None:
    readings = [reading(day, 8, 5, 100 + day) for day in range(1, 6)]  # 08:05 on five days
    (point,) = agp_profile(readings, WARSAW)
    assert point.minute == 8 * 60  # the 08:00 to 08:15 bucket
    assert point.count == 5
    assert point.p50 == 103
    assert point.p5 < point.p25 < point.p50 < point.p75 < point.p95


def test_buckets_with_too_few_readings_are_left_out() -> None:
    readings = [reading(1, 8, 0, 100), reading(2, 8, 0, 110)]
    assert agp_profile(readings, WARSAW) == []


def test_profile_is_in_local_time_and_ordered() -> None:
    readings = [reading(day, h, 0, 100) for day in (1, 2, 3) for h in (22, 3)]
    minutes = [p.minute for p in agp_profile(readings, WARSAW)]
    assert minutes == [3 * 60, 22 * 60]


def test_figure_has_bands_median_and_target_band() -> None:
    readings = [reading(day, 8, 0, 100 + 10 * day) for day in range(1, 6)]
    figure = agp_figure(agp_profile(readings, WARSAW), DisplayUnit.MGDL, low=70, high=180)
    named = [trace["name"] for trace in figure["data"] if "name" in trace]
    assert named == ["5th to 95th percentile", "25th to 75th percentile", "Median"]
    median = figure["data"][-1]
    assert median["x"] == [8.0]
    assert median["y"] == [130]
    (band,) = figure["layout"]["shapes"]
    assert (band["y0"], band["y1"]) == (70, 180)
    assert figure["layout"]["xaxis"]["range"] == [0, 24]


def test_each_band_is_drawn_between_two_edges() -> None:
    readings = [reading(day, 8, 0, 100 + 10 * day) for day in range(1, 6)]
    data = agp_figure(agp_profile(readings, WARSAW), DisplayUnit.MGDL, low=70, high=180)["data"]
    assert [trace.get("fill") for trace in data] == [None, "tonexty", None, "tonexty", None]
    assert data[0]["y"][0] < data[1]["y"][0]  # 5th below 95th


def test_figure_converts_to_mmol() -> None:
    readings = [reading(day, 8, 0, 180) for day in range(1, 6)]
    figure = agp_figure(agp_profile(readings, WARSAW), DisplayUnit.MMOLL, low=72, high=180)
    assert figure["data"][-1]["y"] == [10.0]
    (band,) = figure["layout"]["shapes"]
    assert (band["y0"], band["y1"]) == (4.0, 10.0)


def test_bucket_width_is_fifteen_minutes() -> None:
    start = datetime(2026, 10, 1, 8, 0, tzinfo=WARSAW)
    readings = [
        GlucoseReading(
            user_id=1,
            measured_at=(start + timedelta(days=d, minutes=m)).astimezone(UTC),
            value_mgdl=100,
            source=ReadingSource.CGM,
        )
        for d in range(3)
        for m in (0, 14, 15)
    ]
    assert [(p.minute, p.count) for p in agp_profile(readings, WARSAW)] == [
        (480, 6),
        (495, 3),
    ]
