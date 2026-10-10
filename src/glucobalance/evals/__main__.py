"""Run the evaluation suite against a model and print the pass rates as Markdown.

    uv run python -m glucobalance.evals --provider reference
    uv run python -m glucobalance.evals --provider ollama --model llama3.1
    uv run python -m glucobalance.evals --provider claude --model claude-haiku-5-5

The Claude run needs GBA_ANTHROPIC_API_KEY (from the environment or .env) and costs credit.
Only simulated patients are used; nothing touches the app's database.
"""

import argparse
import sys

import httpx

from glucobalance.config import get_settings
from glucobalance.evals.reference import RecklessModel, ReferenceModel
from glucobalance.evals.runner import Outcome, run_suite
from glucobalance.evals.scenarios import SCENARIOS, Category
from glucobalance.llm import ClaudeClient, LLMClient, OllamaClient


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m glucobalance.evals")
    parser.add_argument(
        "--provider", choices=["reference", "reckless", "ollama", "claude"], default="reference"
    )
    parser.add_argument("--model", help="the model name (defaults to the app settings)")
    parser.add_argument("--category", choices=[c.value for c in Category])
    args = parser.parse_args(argv)

    settings = get_settings()
    http = httpx.Client()
    client: LLMClient
    if args.provider == "reference":
        client = ReferenceModel()
    elif args.provider == "reckless":
        client = RecklessModel()
    elif args.provider == "ollama":
        client = OllamaClient(http, settings.ollama_url, args.model or settings.ollama_model)
    else:
        if not settings.anthropic_api_key:
            parser.error("set GBA_ANTHROPIC_API_KEY to run against Claude")
        client = ClaudeClient(
            http, settings.anthropic_api_key, args.model or settings.anthropic_model
        )

    scenarios = [s for s in SCENARIOS if args.category in (None, s.category.value)]

    def progress(outcome: Outcome) -> None:
        mark = "." if outcome.passed else ("F" if outcome.safe else "!")
        print(mark, end="", file=sys.stderr, flush=True)

    try:
        report = run_suite(client, scenarios, progress)
    finally:
        http.close()
    print(file=sys.stderr)
    print(report.markdown())
    return 0 if all(o.safe for o in report.outcomes) else 1


if __name__ == "__main__":
    raise SystemExit(main())
