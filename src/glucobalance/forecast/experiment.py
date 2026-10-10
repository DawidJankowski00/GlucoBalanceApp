"""The experiment: train on some patients, test on later data and on unseen patients, report.

Two test sets answer two questions:

- **later data** (the last 30% of each training patient's days): how well does the model do
  for people it has learned from, on days it has not seen?
- **unseen patients**: how well does it do for someone new? That is the honest number for a
  new user of the app.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from glucobalance.forecast.evaluation import WARNING_LINES, ClarkeZone, Score, score, split_by_time
from glucobalance.forecast.features import FEATURE_NAMES, Sample, build_samples
from glucobalance.forecast.history import History
from glucobalance.forecast.models import Forecaster, GradientBoosting, LastValue, LinearTrend
from glucobalance.forecast.warning import WARN_BELOW_MGDL

TRAIN_SHARE = 0.7


@dataclass(frozen=True, slots=True)
class ExperimentResult:
    source: str
    train_patients: int
    test_patients: int
    days: int
    train_samples: int
    later: list[Score]  # one per model, baselines first
    unseen: list[Score]
    model: GradientBoosting


def run_experiment(
    train: Sequence[History], unseen: Sequence[History], *, source: str, days: int
) -> ExperimentResult:
    """Train gradient boosting and score it against both baselines on both test sets."""
    train_samples: list[Sample] = []
    later_samples: list[Sample] = []
    for history in train:
        first, rest = split_by_time(build_samples(history), TRAIN_SHARE)
        train_samples += first
        later_samples += rest
    unseen_samples = [s for history in unseen for s in build_samples(history)]
    model = GradientBoosting.train(train_samples)
    models: list[Forecaster] = [LastValue(), LinearTrend(), model]
    return ExperimentResult(
        source=source,
        train_patients=len(train),
        test_patients=len(unseen),
        days=days,
        train_samples=len(train_samples),
        later=[score(m, later_samples) for m in models],
        unseen=[score(m, unseen_samples) for m in models],
        model=model,
    )


def _percent(share: float | None) -> str:
    return "n/a" if share is None else f"{share * 100:.0f}%"


def _table(title: str, scores: Sequence[Score]) -> list[str]:
    lines = [
        f"### {title} ({scores[0].samples:,} forecasts)",
        "",
        "| Model | RMSE (mg/dL) | MAE (mg/dL) | Zone A | Zone B | Zone C | Zone D | Zone E |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for s in scores:
        zones = " | ".join(f"{s.zones[z] * 100:.1f}%" for z in ClarkeZone)
        lines.append(f"| {s.model} | {s.rmse:.1f} | {s.mae:.1f} | {zones} |")
    lines += [
        "",
        "Lows caught: moments at or above 70 mg/dL that were below 70 mg/dL 30 minutes later.",
        "",
        "| Model | Warn below | Lows caught | Warnings that were right | Missed | False alarms |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for s in scores:
        for line in WARNING_LINES:
            low = s.lows[line]
            marker = " (app)" if line == WARN_BELOW_MGDL else ""
            lines.append(
                f"| {s.model} | {line}{marker} | {_percent(low.sensitivity)} "
                f"| {_percent(low.precision)} | {low.missed} | {low.false_alerts} |"
            )
    return lines + [""]


def report_markdown(result: ExperimentResult, *, generated_on: date) -> str:
    """The results as Markdown, for ``docs/forecast/report.md``."""
    lines = [
        "# Forecast report",
        "",
        f"Generated on {generated_on.isoformat()} by `uv run python -m glucobalance.forecast`.",
        "Do not edit by hand; run the command again instead.",
        "",
        f"- Data: {result.source}, {result.days} days per patient, one reading every 5 minutes.",
        f"- Training: the first {TRAIN_SHARE:.0%} of the days of {result.train_patients} "
        f"patients ({result.train_samples:,} forecasts).",
        f"- Tested on the remaining days of those patients, and on {result.test_patients} "
        "patients the model never saw.",
        "- Horizon: 30 minutes. Features: " + ", ".join(f"`{n}`" for n in FEATURE_NAMES) + ".",
        "",
        "Clarke zones: A is clinically accurate, B is off but harmless, C would cause an "
        "unneeded correction, D misses a low or high that needed treatment, E confuses a low "
        "with a high.",
        "",
    ]
    lines += _table("Later days of the training patients", result.later)
    lines += _table("Unseen patients", result.unseen)
    lines += [
        "## Reading these numbers honestly",
        "",
        "- The patients are synthetic. Their glucose follows a simple model with clean meal "
        "and insulin effects and sensor noise, so it is easier to predict than real data. "
        "Published 30-minute forecasts on real CGM data report RMSEs of roughly 18 to 30 "
        "mg/dL; expect numbers in that range for a real person, not the ones above.",
        "- The model only knows the carbs and insulin that were logged. Unlogged snacks, "
        "exercise, illness and stress are invisible to it.",
        "- Lows are rare, so the low-warning numbers rest on a few hundred events.",
        '- The app never shows the predicted value; it only shows a "likely low soon" '
        "warning, and only when the CGM data is fresh. See `docs/forecast/model-card.md`.",
        "",
    ]
    return "\n".join(lines)
