"""The assistant's evaluation suite: simulated patients, scenarios and a runner."""

from glucobalance.evals.reference import RecklessModel, ReferenceModel
from glucobalance.evals.runner import Outcome, Report, run_scenario, run_suite, score
from glucobalance.evals.scenarios import SCENARIOS, Category, Scenario

__all__ = [
    "SCENARIOS",
    "Category",
    "Outcome",
    "RecklessModel",
    "ReferenceModel",
    "Report",
    "Scenario",
    "run_scenario",
    "run_suite",
    "score",
]
