"""The forecasters: two baselines and a gradient boosting model, behind one small interface.

A baseline is the simplest prediction that is still sensible. A learned model is only worth
having if it beats them, so both are always reported next to it:

- ``LastValue``: glucose in 30 minutes equals glucose now.
- ``LinearTrend``: the last 30 minutes' straight-line trend continues for 30 more minutes,
  which is what a CGM trend arrow implies.

``GradientBoosting`` uses scikit-learn's ``HistGradientBoostingRegressor``. Gradient boosting
builds many small decision trees one after another, each one correcting the errors the
previous trees still make. The "histogram" variant first sorts each feature into at most 255
bins, which makes training fast on tens of thousands of rows. It predicts the 30-minute change
and adds it to the current value.

A trained model is saved with joblib, which uses Python's pickle format. Loading a pickle can
run code, so only load model files you trained yourself (ADR 0019).
"""

from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

import joblib
import numpy as np
from numpy.typing import NDArray
from sklearn.ensemble import HistGradientBoostingRegressor

from glucobalance.forecast.features import FEATURE_NAMES, GLUCOSE, HORIZON, SLOPE_30, Sample

HORIZON_MINUTES = HORIZON.total_seconds() / 60
SEED = 0


class Forecaster(Protocol):
    """Predicts glucose (mg/dL) at the horizon for each row of features."""

    @property
    def name(self) -> str: ...

    def predict(self, rows: Sequence[Sequence[float]]) -> list[float]: ...


def matrix(rows: Sequence[Sequence[float]]) -> NDArray[np.float64]:
    return np.asarray(rows, dtype=np.float64).reshape(-1, len(FEATURE_NAMES))


class LastValue:
    name = "last value"

    def predict(self, rows: Sequence[Sequence[float]]) -> list[float]:
        return [float(row[GLUCOSE]) for row in rows]


class LinearTrend:
    name = "linear trend"

    def predict(self, rows: Sequence[Sequence[float]]) -> list[float]:
        return [float(row[GLUCOSE] + row[SLOPE_30] * HORIZON_MINUTES) for row in rows]


class GradientBoosting:
    name = "gradient boosting"

    def __init__(self, model: HistGradientBoostingRegressor) -> None:
        self.model = model

    @classmethod
    def train(cls, samples: Sequence[Sample]) -> "GradientBoosting":
        """Fit on samples that have a known outcome."""
        known = [s for s in samples if s.target is not None]
        if not known:
            raise ValueError("there are no samples with a known outcome to train on")
        model = HistGradientBoostingRegressor(
            max_iter=300,
            learning_rate=0.05,
            max_leaf_nodes=31,
            min_samples_leaf=40,
            l2_regularization=1.0,
            random_state=SEED,
        )
        model.fit(matrix([s.features for s in known]), np.asarray([s.target for s in known]))
        return cls(model)

    def predict(self, rows: Sequence[Sequence[float]]) -> list[float]:
        if not rows:
            return []
        change = self.model.predict(matrix(rows))
        return [float(row[GLUCOSE] + delta) for row, delta in zip(rows, change, strict=True)]

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump({"features": FEATURE_NAMES, "model": self.model}, path)

    @classmethod
    def load(cls, path: Path) -> "GradientBoosting":
        """Load a model saved by ``save``. Pickle-based: only load your own files."""
        saved = joblib.load(path)
        if not isinstance(saved, dict) or tuple(saved.get("features", ())) != FEATURE_NAMES:
            raise ValueError(f"{path} was trained with different features; train it again")
        model = saved["model"]
        if not isinstance(model, HistGradientBoostingRegressor):
            raise ValueError(f"{path} does not hold a gradient boosting model")
        return cls(model)


def load_forecaster(path: str | Path | None) -> Forecaster:
    """The trained model at ``path``, or the linear trend baseline when there is none."""
    if path is None or not Path(path).is_file():
        return LinearTrend()
    return GradientBoosting.load(Path(path))
