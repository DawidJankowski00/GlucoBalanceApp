"""Train and evaluate the forecast, save the model and write the report.

    uv run python -m glucobalance.forecast
    uv run python -m glucobalance.forecast --train-patients 12 --days 45
    uv run --group sim python -m glucobalance.forecast --source simglucose   # slow

Then point the app at the model with ``GBA_FORECAST_MODEL_PATH=models/forecast.joblib``.
"""

import argparse
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path

from glucobalance.forecast.evaluation import ClarkeZone
from glucobalance.forecast.experiment import report_markdown, run_experiment
from glucobalance.forecast.history import History, synthetic_history

# Different seed ranges, so no unseen patient shares a random stream with a training one.
TRAIN_SEEDS_FROM = 1
UNSEEN_SEEDS_FROM = 1001
SIMGLUCOSE_TRAIN = ("adolescent#001", "adolescent#002", "adult#001", "adult#002", "child#001")
SIMGLUCOSE_UNSEEN = ("adolescent#003", "adult#003")


def _simglucose(patients: Sequence[str], days: int) -> list[History]:  # pragma: no cover
    from glucobalance.seed import simulate

    start = datetime(2026, 1, 1, tzinfo=UTC) - timedelta(days=days)
    histories = []
    for seed, patient in enumerate(patients, start=1):
        data = simulate(days, start, patient=patient, seed=seed)
        histories.append(
            History(
                readings=tuple(data.readings),
                carbs=tuple((at, float(g)) for at, g in data.meals),
                boluses=tuple((at, float(u)) for at, u in data.boluses),
            )
        )
    return histories


def main(argv: Sequence[str] | None = None) -> int:  # pragma: no cover - thin CLI wrapper
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", choices=("synthetic", "simglucose"), default="synthetic")
    parser.add_argument("--train-patients", type=int, default=8)
    parser.add_argument("--test-patients", type=int, default=3)
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--model-out", type=Path, default=Path("models/forecast.joblib"))
    parser.add_argument("--report", type=Path, default=Path("docs/forecast/report.md"))
    args = parser.parse_args(argv)

    if args.source == "simglucose":
        train = _simglucose(SIMGLUCOSE_TRAIN, args.days)
        unseen = _simglucose(SIMGLUCOSE_UNSEEN, args.days)
        source = "simglucose (UVA/Padova) virtual patients"
    else:
        print(f"Generating {args.train_patients + args.test_patients} synthetic patients...")
        train = [
            synthetic_history(args.days, TRAIN_SEEDS_FROM + i) for i in range(args.train_patients)
        ]
        unseen = [
            synthetic_history(args.days, UNSEEN_SEEDS_FROM + i) for i in range(args.test_patients)
        ]
        source = "synthetic patients (glucobalance.forecast.history)"
    print("Training and scoring...")
    result = run_experiment(train, unseen, source=source, days=args.days)
    result.model.save(args.model_out)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        report_markdown(result, generated_on=datetime.now(UTC).date()), encoding="utf-8"
    )
    for title, scores in (("later days", result.later), ("unseen patients", result.unseen)):
        print(f"{title}:")
        for s in scores:
            print(f"  {s.model:<18} RMSE {s.rmse:5.1f}  zone A {s.zones[ClarkeZone.A] * 100:5.1f}%")
    print(f"Model saved to {args.model_out}, report written to {args.report}.")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
