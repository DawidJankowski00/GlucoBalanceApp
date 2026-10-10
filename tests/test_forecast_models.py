"""The baselines, the gradient boosting model, saving and loading, and the experiment."""

from datetime import date
from pathlib import Path

import joblib
import pytest

from glucobalance.forecast.experiment import report_markdown, run_experiment
from glucobalance.forecast.features import FEATURE_NAMES, build_samples
from glucobalance.forecast.history import synthetic_history
from glucobalance.forecast.models import (
    GradientBoosting,
    LastValue,
    LinearTrend,
    load_forecaster,
)


def row(**values: float) -> list[float]:
    return [values.get(name, 0.0) for name in FEATURE_NAMES]


def test_baselines() -> None:
    rows = [row(glucose=120, slope_30=-1.5), row(glucose=200, slope_30=2)]
    assert LastValue().predict(rows) == [120, 200]
    assert LinearTrend().predict(rows) == [75, 260]


def test_synthetic_patients_are_repeatable_and_plausible() -> None:
    a = synthetic_history(2, seed=7)
    assert a == synthetic_history(2, seed=7)
    assert a != synthetic_history(2, seed=8)
    assert len(a.readings) == 2 * 24 * 12
    assert all(40 <= value <= 400 for _, value in a.readings)
    assert len(a.carbs) >= 6
    assert a.boluses


@pytest.fixture(scope="module")
def trained() -> GradientBoosting:
    return GradientBoosting.train(build_samples(synthetic_history(4, seed=1)))


def test_gradient_boosting_beats_last_value_on_new_days(trained: GradientBoosting) -> None:
    test = build_samples(synthetic_history(2, seed=2))
    rows = [s.features for s in test]
    actual = [s.glucose + (s.target or 0) for s in test]

    def error(predicted: list[float]) -> float:
        return sum(abs(a - p) for a, p in zip(actual, predicted, strict=True)) / len(actual)

    assert error(trained.predict(rows)) < error(LastValue().predict(rows))
    assert trained.predict([]) == []
    with pytest.raises(ValueError):
        GradientBoosting.train([])


def test_saved_models_load_back(trained: GradientBoosting, tmp_path: Path) -> None:
    path = tmp_path / "models" / "forecast.joblib"
    trained.save(path)
    rows = [row(glucose=150, delta_15=-20, slope_30=-1.2, iob=2)]
    loaded = load_forecaster(path)
    assert isinstance(loaded, GradientBoosting)
    assert loaded.predict(rows) == trained.predict(rows)


def test_without_a_model_the_linear_trend_is_used(tmp_path: Path) -> None:
    assert isinstance(load_forecaster(None), LinearTrend)
    assert isinstance(load_forecaster(tmp_path / "missing.joblib"), LinearTrend)


def test_a_model_with_other_features_is_refused(trained: GradientBoosting, tmp_path: Path) -> None:
    path = tmp_path / "old.joblib"
    joblib.dump({"features": ("glucose",), "model": trained.model}, path)
    with pytest.raises(ValueError, match="different features"):
        GradientBoosting.load(path)
    joblib.dump({"features": FEATURE_NAMES, "model": "not a model"}, path)
    with pytest.raises(ValueError, match="gradient boosting"):
        GradientBoosting.load(path)


def test_the_experiment_reports_every_model_on_both_test_sets() -> None:
    train = [synthetic_history(3, seed=1), synthetic_history(3, seed=2)]
    unseen = [synthetic_history(2, seed=1001)]
    result = run_experiment(train, unseen, source="synthetic", days=3)
    assert [s.model for s in result.later] == ["last value", "linear trend", "gradient boosting"]
    assert [s.model for s in result.unseen] == ["last value", "linear trend", "gradient boosting"]
    assert result.train_samples > 0

    report = report_markdown(result, generated_on=date(2026, 10, 10))
    assert "# Forecast report" in report
    assert "Generated on 2026-10-10" in report
    assert "### Unseen patients" in report
    assert "| gradient boosting | 80 (app) |" in report
    assert "synthetic" in report
