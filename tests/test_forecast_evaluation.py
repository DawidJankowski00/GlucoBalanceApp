"""Error measures, the Clarke error grid, lows caught and the time split."""

from datetime import UTC, datetime, timedelta

import pytest

from glucobalance.forecast.evaluation import (
    ClarkeZone,
    clarke_zone,
    low_detection,
    mae,
    rmse,
    score,
    split_by_time,
)
from glucobalance.forecast.features import FEATURE_NAMES, Sample
from glucobalance.forecast.models import LastValue
from glucobalance.forecast.warning import likely_low_soon

T0 = datetime(2026, 10, 9, tzinfo=UTC)


@pytest.mark.parametrize(
    ("actual", "predicted", "zone"),
    [
        (100, 100, ClarkeZone.A),
        (100, 119, ClarkeZone.A),  # within 20%
        (60, 50, ClarkeZone.A),  # both below 70
        (100, 125, ClarkeZone.B),  # off, but harmless
        (100, 220, ClarkeZone.C),  # would cause an unneeded correction
        (150, 25, ClarkeZone.C),
        (300, 150, ClarkeZone.D),  # misses a high
        (50, 100, ClarkeZone.D),  # misses a low
        (250, 60, ClarkeZone.E),  # a high read as a low
        (50, 200, ClarkeZone.E),  # a low read as a high
    ],
)
def test_clarke_zones(actual: float, predicted: float, zone: ClarkeZone) -> None:
    assert clarke_zone(actual, predicted) is zone


def test_rmse_counts_big_misses_more_than_mae() -> None:
    actual = [100.0, 100.0, 100.0, 100.0]
    predicted = [100.0, 100.0, 100.0, 120.0]
    assert mae(actual, predicted) == 5
    assert rmse(actual, predicted) == 10
    with pytest.raises(ValueError):
        rmse([], [])
    with pytest.raises(ValueError):
        mae([1.0], [1.0, 2.0])


def test_the_warning_fires_only_on_a_predicted_low_while_not_low_yet() -> None:
    assert likely_low_soon(95, 75)
    assert not likely_low_soon(95, 85)
    assert not likely_low_soon(65, 50)  # already low: the live page shows that instead
    assert likely_low_soon(95, 85, warn_below=90)


def test_low_detection_counts_hits_misses_and_false_alarms() -> None:
    current = [100.0, 100.0, 100.0, 100.0, 60.0]
    actual = [65.0, 65.0, 110.0, 100.0, 50.0]
    predicted = [75.0, 95.0, 78.0, 100.0, 50.0]
    found = low_detection(current, actual, predicted)
    assert (found.true_alerts, found.missed, found.false_alerts) == (1, 1, 1)
    assert found.sensitivity == 0.5
    assert found.precision == 0.5
    assert low_detection([100.0], [100.0], [100.0]).sensitivity is None


def sample(minutes: int, glucose: int, target: float | None) -> Sample:
    features = (float(glucose),) + (0.0,) * (len(FEATURE_NAMES) - 1)
    return Sample(T0 + timedelta(minutes=minutes), glucose, features, target)


def test_split_by_time_trains_on_the_past() -> None:
    samples = [sample(m, 100, 0.0) for m in (30, 10, 20, 0, 40)]
    first, rest = split_by_time(samples, 0.6)
    assert [s.at.minute for s in first] == [0, 10, 20]
    assert [s.at.minute for s in rest] == [30, 40]
    with pytest.raises(ValueError):
        split_by_time(samples, 1.0)


def test_score_puts_it_together() -> None:
    samples = [sample(0, 100, 0.0), sample(5, 100, 40.0), sample(10, 90, None)]
    result = score(LastValue(), samples)
    assert result.samples == 2
    assert result.mae == 20
    assert result.zones[ClarkeZone.A] == 0.5
    assert result.zones[ClarkeZone.B] == 0.5
    assert set(result.lows) == {70, 80, 90}
    with pytest.raises(ValueError):
        score(LastValue(), [sample(0, 100, None)])
