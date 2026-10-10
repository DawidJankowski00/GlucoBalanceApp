"""How good is a forecast? RMSE, MAE, the Clarke error grid and how well lows are caught.

- **RMSE** (root mean squared error) squares each error before averaging, so a few large
  misses count heavily. **MAE** (mean absolute error) is the plain average miss in mg/dL.
- The **Clarke error grid** (Clarke et al., 1987) sorts each (actual, predicted) pair into a
  zone by what a person might do with the wrong number. A: within 20% (or both below 70),
  clinically fine. B: off by more, but still harmless. C: would cause an unneeded correction.
  D: misses a low or high that needed treatment. E: confuses a low with a high. A good
  forecast has nearly everything in A and B and nothing in E.
- **Lows caught** asks the question the warning exists for: of the moments in range now that
  are below 70 mg/dL 30 minutes later, how many did the forecast flag (sensitivity), and how
  many of the flags were right (precision)? Both are reported for several warning lines,
  because a warning that misses lows is useless and one that cries wolf is ignored.

Samples are split by time, never at random: the model trains on the earlier part of each
patient's data and is tested on the later part, plus on patients it has never seen. A random
split would test on moments five minutes away from training ones and flatter the model.
"""

import math
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from glucobalance.forecast.features import Sample
from glucobalance.forecast.models import Forecaster
from glucobalance.forecast.warning import LOW_MGDL, WARN_BELOW_MGDL, likely_low_soon

# Warning lines compared in the report; the app uses WARN_BELOW_MGDL.
WARNING_LINES = (70, WARN_BELOW_MGDL, 90)


class ClarkeZone(StrEnum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"
    E = "E"


def clarke_zone(actual: float, predicted: float) -> ClarkeZone:
    """The Clarke error grid zone of one pair, both in mg/dL."""
    if (actual <= 70 and predicted <= 70) or 0.8 * actual <= predicted <= 1.2 * actual:
        return ClarkeZone.A
    if (actual >= 180 and predicted <= 70) or (actual <= 70 and predicted >= 180):
        return ClarkeZone.E
    if (70 <= actual <= 290 and predicted >= actual + 110) or (
        130 <= actual <= 180 and predicted <= 7 / 5 * actual - 182
    ):
        return ClarkeZone.C
    if (
        (actual >= 240 and 70 <= predicted <= 180)
        or (actual <= 175 / 3 and 70 <= predicted <= 180)
        or (175 / 3 <= actual <= 70 and predicted >= 6 / 5 * actual)
    ):
        return ClarkeZone.D
    return ClarkeZone.B


def rmse(actual: Sequence[float], predicted: Sequence[float]) -> float:
    _check(actual, predicted)
    pairs = zip(actual, predicted, strict=True)
    return math.sqrt(sum((a - p) ** 2 for a, p in pairs) / len(actual))


def mae(actual: Sequence[float], predicted: Sequence[float]) -> float:
    _check(actual, predicted)
    return sum(abs(a - p) for a, p in zip(actual, predicted, strict=True)) / len(actual)


def _check(actual: Sequence[float], predicted: Sequence[float]) -> None:
    if not actual or len(actual) != len(predicted):
        raise ValueError("need the same, non-zero number of actual and predicted values")


@dataclass(frozen=True, slots=True)
class LowDetection:
    """Moments in range now: did the forecast flag the ones that were low 30 minutes later?"""

    true_alerts: int
    false_alerts: int
    missed: int

    @property
    def sensitivity(self) -> float | None:
        lows = self.true_alerts + self.missed
        return self.true_alerts / lows if lows else None

    @property
    def precision(self) -> float | None:
        alerts = self.true_alerts + self.false_alerts
        return self.true_alerts / alerts if alerts else None


def low_detection(
    current: Sequence[float],
    actual: Sequence[float],
    predicted: Sequence[float],
    *,
    low_mgdl: int = LOW_MGDL,
    warn_below: int = WARN_BELOW_MGDL,
) -> LowDetection:
    true_alerts = false_alerts = missed = 0
    for now, later, guess in zip(current, actual, predicted, strict=True):
        if now < low_mgdl:
            continue  # already low: the live page says so, the forecast adds nothing
        alert = likely_low_soon(now, guess, low_mgdl=low_mgdl, warn_below=warn_below)
        low = later < low_mgdl
        if alert and low:
            true_alerts += 1
        elif alert:
            false_alerts += 1
        elif low:
            missed += 1
    return LowDetection(true_alerts, false_alerts, missed)


@dataclass(frozen=True, slots=True)
class Score:
    model: str
    samples: int
    rmse: float
    mae: float
    zones: dict[ClarkeZone, float]  # share of samples in each zone, 0 to 1
    lows: dict[int, LowDetection]  # by warning line


def score(model: Forecaster, samples: Sequence[Sample]) -> Score:
    """Evaluate ``model`` on samples with known outcomes."""
    known = [s for s in samples if s.target is not None]
    if not known:
        raise ValueError("there are no samples with a known outcome to score")
    predicted = model.predict([s.features for s in known])
    current = [float(s.glucose) for s in known]
    actual = [s.glucose + s.target for s in known if s.target is not None]
    counts = Counter(clarke_zone(a, p) for a, p in zip(actual, predicted, strict=True))
    return Score(
        model=model.name,
        samples=len(known),
        rmse=rmse(actual, predicted),
        mae=mae(actual, predicted),
        zones={zone: counts[zone] / len(known) for zone in ClarkeZone},
        lows={
            line: low_detection(current, actual, predicted, warn_below=line)
            for line in WARNING_LINES
        },
    )


def split_by_time(
    samples: Sequence[Sample], train_share: float
) -> tuple[list[Sample], list[Sample]]:
    """The earliest ``train_share`` of the samples for training, the rest for testing."""
    if not 0 < train_share < 1:
        raise ValueError("train_share must be between 0 and 1")
    ordered = sorted(samples, key=lambda s: s.at)
    cut = round(len(ordered) * train_share)
    return ordered[:cut], ordered[cut:]
