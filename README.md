# GlucoBalanceApp

GlucoBalanceApp (GBA) is a companion app for people with Type 1 diabetes. It is planned as a Python web app that logs glucose and insulin, rotates injection and infusion sites, sends care reminders, imports readings from a CGM, and includes an AI assistant that spots patterns and suggests small, capped adjustments for the user to confirm.

It is also a portfolio project: it is meant to show backend engineering, AI engineering with real guardrails, and data work in a domain where safety matters.

> **Not a medical device.** GBA is a personal, educational project. It is not medical advice, it never changes a dose by itself, and any insulin settings should be agreed with your diabetes care team.

## Project status

**Planning stage. There is no application code in this repository yet.** Everything below describes what is planned, not what exists. Development will happen in small stages (see [Roadmap](#roadmap)), and this README will be updated as each stage lands.

## Planned features

### Two settings that shape the app

At onboarding the user picks two options, and every screen, reminder and assistant feature adapts to them.

**Insulin delivery: pump or pens**

| | Pump | Pens |
|---|---|---|
| Site rotation | One infusion site per set change, least recently used site first | One point per injection, tracked separately for rapid-acting and long-acting insulin |
| Unavailable sites | Mark a site as blocked | Mark a site as blocked until a date or permanently, and skip to the next best site |
| Main reminder | Change the infusion set every N days (configurable, default 3) | Daily long-acting dose, with a missed-dose alert |
| Other reminders | Reservoir refill, pump battery | Pen-needle change, opened-pen expiry |

**Glucose monitoring: glucometer or CGM**

| | Glucometer | CGM |
|---|---|---|
| Data entry | Quick manual form with a tag (fasting, before meal, after meal, bedtime, night) | Automatic import every few minutes |
| Reminders | Glucose check reminders at chosen times | Sensor change and sensor site rotation |
| Alerts | Recheck reminder after a low or high entry | High, low and fast-falling alerts |
| Statistics | Averages by time of day, with a warning when data is sparse | Time in range, variability, ambulatory glucose profile |

### CGM import from LibreLinkUp

Libre readings will be imported through LibreLinkUp, the same way [GlucoDataHandler](https://github.com/pachi81/GlucoDataHandler) does. The app will use its own follower account, because several apps sharing one account trigger "429 Too Many Requests" and false login errors. A simulator ([simglucose](https://github.com/jxx123/simglucose)) will feed tests, CI and the public demo, so they never call Abbott's servers.

LibreLinkUp access is unofficial and could change, so CGM sources sit behind one interface and another source (for example Nightscout) can be added without touching the rest of the app.

### AI dosing assistant

The assistant is split in two:

- **Plain, tested Python computes every number:** the bolus calculator, insulin on board, and the adjustment suggester that turns detected patterns (such as repeated night lows or post-breakfast highs) into small changes capped by the user's settings.
- **An LLM explains and converses:** it reads data only through tools, explains what it sees with the supporting readings, and presents suggestions that the user accepts or rejects.

Planned guardrails include: any dose number in a reply must match a tool result or the reply is blocked; no suggestions when glucose is low or CGM data is stale; caps on bolus size and on how much a setting can change; nothing is ever applied automatically. The assistant will be tested with an evaluation suite of simulated-patient scenarios and adversarial prompts, run in CI.

### Other planned features

Analytics and a printable clinic report, carb logging with food search (Open Food Facts), a hypo log with a recheck reminder, data export and account deletion, and later options such as sick-day mode, an exercise log, supply stock tracking, an optional 30-minute glucose forecast model, and a Polish translation.

## Planned tech stack

| Layer | Choice |
|---|---|
| Language | Python 3.12, managed with uv |
| API | FastAPI, Pydantic v2 |
| Database | PostgreSQL (SQLite for tests), SQLAlchemy 2, Alembic |
| UI | Jinja2 templates, HTMX, Tailwind, installable as a PWA |
| Charts | Plotly |
| Background jobs | APScheduler |
| Notifications | Web Push (pywebpush), optional Telegram bot |
| Analytics / ML | pandas, numpy, scikit-learn or LightGBM |
| Simulated patients | simglucose |
| LLM | Provider-agnostic client: Ollama for local development, Claude API for the demo |
| Quality | pytest, hypothesis, ruff, mypy, pre-commit |
| CI / packaging | GitHub Actions, Docker Compose |

The app is planned as a modular monolith: one FastAPI app split into domain modules (settings, glucose, insulin, sites, reminders, analytics, assistant), with adapter interfaces for CGM sources and LLM providers.

## Roadmap

Each stage ends with something that can be demonstrated.

- [ ] **Stage 0: Foundations.** Project tooling, FastAPI skeleton, Docker Compose, CI.
- [ ] **Stage 1: Domain model and data layer.** Core entities, migrations, simulated seed data.
- [ ] **Stage 2: Accounts, onboarding and settings.** Sign-up, the two settings, feature flags.
- [ ] **Stage 3: Glucose logging.** Manual entry, insulin and carb logging, daily charts.
- [ ] **Stage 4: Site rotation engine.** Next-site suggestions for pump and pens, blocked sites, body map.
- [ ] **Stage 5: Reminders and notifications.** Scheduled reminders and Web Push.
- [ ] **Stage 6: CGM integration.** LibreLinkUp client and simulator source.
- [ ] **Stage 7: Analytics and reports.** Time in range, glucose profile, pattern detection, PDF report.
- [ ] **Stage 8: AI assistant, deterministic core.** Bolus calculator, insulin on board, capped suggestions.
- [ ] **Stage 9: AI assistant, LLM agent.** Tool-calling agent, guardrails, evaluation suite.
- [ ] **Stage 10: Forecast model (optional).** 30-minute glucose prediction with honest error reporting.
- [ ] **Stage 11: Polish and launch.** Demo accounts, security pass, public demo on simulated data.

## Getting started

There is nothing to install or run yet. Setup instructions will be added here in Stage 0.

## Data and privacy

Real health data is meant to stay on the user's own machine. The public demo will only ever hold simulated patients.

## Licence

GlucoBalanceApp is released under the [MIT Licence](LICENSE).
