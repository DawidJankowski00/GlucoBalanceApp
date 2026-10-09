# CLAUDE.md

GlucoBalanceApp (GBA): a personal, educational Type 1 diabetes companion app. **Not a medical device.**

**Read `PLAN.md` at the start of every session.** It holds the stages, the design rules, the safety limits and the working rules. Work on the current stage only.

## Working rules (short form; full list in PLAN.md)

- **Explain before coding.** Introduce any new library, pattern or domain term briefly before using it. The owner wants to understand every segment.
- **Plan first.** Propose a short plan for a stage or task and wait for approval.
- **Tests first for logic.** Write failing tests for anything with rules, show them, then implement.
- **The owner writes the critical code:** bolus calculator, insulin-on-board model, site rotation algorithm. Help with tests, review and explanation only, unless asked.
- **Never commit or push without asking.** Small commits, conventional messages (`feat:`, `fix:`, `test:`, `docs:`, `chore:`). No Claude attribution lines in commits.
- **Explain what you did** after each task, then stop. Tick finished tasks in `PLAN.md`.
- **Record significant decisions** as an ADR in `docs/adr/`.

## Commands

```bash
uv sync                  # install dependencies
uv run ruff check        # lint
uv run ruff format       # format
uv run mypy              # type check (strict)
uv run pytest            # tests
uv run uvicorn glucobalance.main:app --reload   # run the app
uv run alembic upgrade head                     # apply database migrations
uv run alembic revision --autogenerate -m "..." # draft a migration from model changes
docker compose up --build                       # app + PostgreSQL
```

Run all four checks (ruff check, ruff format, mypy, pytest) before calling a task finished.

## Conventions

- src layout: code in `src/glucobalance/`, tests in `tests/`.
- Fully typed code (mypy strict), ruff line length 100.
- Glucose is stored in mg/dL and converted only for display.
- Dosing numbers come from deterministic, tested Python; the LLM never computes doses.
- Domain terms are explained in `docs/glossary.md`.
