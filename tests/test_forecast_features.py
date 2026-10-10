"""The feature pipeline: lags, trend, insulin and carbs on board, and no peeking ahead."""

import math
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from glucobalance.forecast.features import (
    FEATURE_NAMES,
    FeatureBuilder,
    build_samples,
    latest_sample,
    slope,
)
from glucobalance.forecast.history import History

T0 = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)


def every_5_minutes(values: list[int], start: datetime = T0) -> tuple[tuple[datetime, int], ...]:
    return tuple((start + timedelta(minutes=5 * i), v) for i, v in enumerate(values))


def named(features: tuple[float, ...]) -> dict[str, float]:
    return dict(zip(FEATURE_NAMES, features, strict=True))


def test_slope_is_mg_dl_per_minute() -> None:
    # (minutes ago, value): rising 10 mg/dL every 5 minutes is 2 mg/dL per minute.
    assert slope([(10, 100), (5, 110), (0, 120)]) == pytest.approx(2.0)
    assert slope([(0, 120)]) == 0.0
    assert slope([(0, 120), (0, 130)]) == 0.0


def test_a_falling_line_gives_its_deltas_and_trend() -> None:
    history = History(readings=every_5_minutes([200 - 4 * i for i in range(7)]))
    row = named(FeatureBuilder(history).features_at(6) or ())
    assert row["glucose"] == 176
    assert row["delta_5"] == -4
    assert row["delta_15"] == -12
    assert row["delta_30"] == -24
    assert row["slope_30"] == pytest.approx(-0.8)
    assert row["bend"] == 0


def test_bend_shows_a_trend_that_is_turning() -> None:
    # Flat for 15 minutes, then falling 5 mg/dL per reading.
    history = History(readings=every_5_minutes([150, 150, 150, 150, 145, 140, 135]))
    row = named(FeatureBuilder(history).features_at(6) or ())
    assert row["bend"] == -15


def test_missing_history_gives_no_row() -> None:
    readings = every_5_minutes([120] * 7)
    without_15 = tuple(r for i, r in enumerate(readings) if i != 3)
    builder = FeatureBuilder(History(readings=without_15))
    assert builder.features_at(len(without_15) - 1) is None
    assert FeatureBuilder(History(readings=readings)).features_at(5) is None  # only 25 min back


def test_a_reading_a_minute_late_still_counts() -> None:
    readings = list(every_5_minutes([120] * 7))
    readings[3] = (readings[3][0] + timedelta(minutes=1), 120)
    assert FeatureBuilder(History(readings=tuple(readings))).features_at(6) is not None


def test_insulin_and_carbs_on_board_fade_in_a_straight_line() -> None:
    now = T0 + timedelta(minutes=30)
    history = History(
        readings=every_5_minutes([120] * 7),
        boluses=((now - timedelta(minutes=120), 4.0), (now - timedelta(minutes=30), 2.0)),
        carbs=((now - timedelta(minutes=90), 60.0), (now + timedelta(minutes=5), 50.0)),
    )
    row = named(FeatureBuilder(history).features_at(6) or ())
    # 4 U two hours into four: half left; 2 U half an hour in: 7/8 left.
    assert row["iob"] == pytest.approx(2 + 1.75)
    assert row["bolus_60"] == pytest.approx(2)
    # 60 g halfway through three hours; the later meal has not happened yet.
    assert row["cob"] == pytest.approx(30)
    assert row["carbs_60"] == 0


def test_time_of_day_uses_the_local_clock() -> None:
    history = History(readings=every_5_minutes([120] * 7))  # last reading 12:30 UTC
    utc = named(FeatureBuilder(history).features_at(6) or ())
    warsaw = named(FeatureBuilder(history, ZoneInfo("Europe/Warsaw")).features_at(6) or ())
    assert utc["hour_cos"] == pytest.approx(math.cos(12.5 / 24 * 2 * math.pi))
    assert warsaw["hour_cos"] == pytest.approx(math.cos(14.5 / 24 * 2 * math.pi))


def test_samples_carry_the_change_30_minutes_later() -> None:
    history = History(readings=every_5_minutes(list(range(100, 165, 5))))  # 13 readings
    samples = build_samples(history)
    # Rows from reading 6 (30 min of history) to reading 6 (the last with 30 min ahead).
    assert [s.glucose for s in samples] == [130]
    assert samples[0].target == 30


def test_features_never_see_the_future() -> None:
    values = [120 + i for i in range(20)]
    changed = values[:10] + [40] * 10
    a = FeatureBuilder(History(readings=every_5_minutes(values))).features_at(9)
    b = FeatureBuilder(History(readings=every_5_minutes(changed))).features_at(9)
    assert a == b


def test_latest_sample_has_no_outcome_yet() -> None:
    sample = latest_sample(History(readings=every_5_minutes([150 - i for i in range(10)])))
    assert sample is not None
    assert sample.glucose == 141
    assert sample.target is None
    assert latest_sample(History(readings=())) is None
