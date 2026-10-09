# GlucoBalanceApp: Project Plan for Claude Code

This file is the working plan for building GlucoBalanceApp (GBA) with Claude Code. Read it at the start of every session before touching code. It is based on the project plan doc ("T1D Companion: Project Plan") and on what is actually in this repository.

> **Not a medical device.** GBA is a personal, educational project and a CV showcase for Python Developer / AI Engineer roles. It never changes a dose by itself, every dosing number comes from deterministic code using settings agreed with a clinician, and the public demo only ever uses simulated patients.

## How to work on this project (read first)

The owner wants to build the app in segments and fully understand every one. Follow these rules in every session:

1. **One stage at a time.** Work only on the current stage (the first stage below with unticked tasks) unless the owner names another one. Do not start the next stage on your own.
2. **Plan before coding.** At the start of a stage, propose a short plan for it (files, modules, tests, new libraries) and wait for the owner to approve or edit it.
3. **Explain new concepts before using them.** When a stage introduces a library, pattern or domain term the owner has not seen in this project yet, explain it briefly first.
4. **Tests first for logic.** For anything with rules (rotation, reminders, calculations, guardrails), write failing tests that describe the behaviour, show them, then implement.
5. **The owner writes the critical code.** The bolus calculator, the insulin-on-board model and the site rotation algorithm are written by the owner by hand. Claude Code helps with tests, review and refactoring for those, and explains rather than writes them unless asked.
6. **Explain what you did, then stop.** After finishing a stage (or a task group within it), summarise what changed and why, which files were touched, and how to run or check it. Then wait for approval before moving on.
7. **Never commit or push without asking.** Use small commits with conventional commit messages (`feat:`, `fix:`, `test:`, `docs:`, `chore:`) once the owner agrees.
8. **Record significant decisions** as a short ADR in `docs/adr/` (once that folder exists), for example HTMX over React, APScheduler over Celery, the LLM guardrail design.
9. **End each stage with a recap.** Offer to quiz the owner on the code from the stage; anything they cannot explain gets rewritten or documented.
10. **Keep this file current.** Tick tasks off here as they are finished and approved, and update "Current state" below.

## Current state of the repository

**What exists today:**

| Path | What it is |
|---|---|
| `README.md` | Project description, planned features, roadmap, disclaimer. Describes the plan, not working features. |
| `.gitignore` | Python, virtualenv, tool caches, secrets. |
| `pyproject.toml` | Project metadata (`glucobalance`, Python >= 3.12, hatchling build) plus all tool config: ruff, mypy (strict), pytest. `httpx` is a runtime dependency (food search). Dev dependency group: ruff, mypy, pytest, pre-commit. |
| `uv.lock` | Pinned dependency versions. Commit it. |
| `src/glucobalance/__init__.py` | Re-exports `MGDL_PER_MMOLL` and `mgdl_to_mmoll()` from `units.py`. |
| `src/glucobalance/units.py` | `DisplayUnit`, `mgdl_to_mmoll()`, `mmoll_to_mgdl()`, `format_glucose()`. |
| `src/glucobalance/db.py` | SQLAlchemy `Base` (with constraint naming convention), `make_engine()`, `make_session_factory()`, `get_session()`. |
| `src/glucobalance/models/` | ORM models: User, UserSettings, SettingsTimeBlock, GlucoseReading, InsulinDose, CarbEntry, BodySite, SiteUse, Reminder, Note; `UTCDateTime` and `str_enum` column types. |
| `src/glucobalance/repositories.py` | One repository per aggregate; flush, never commit. |
| `src/glucobalance/seed.py` | Simulated pump + CGM demo user from simglucose (`uv run --group sim python -m glucobalance.seed`). |
| `alembic.ini`, `migrations/` | Alembic config and migrations; the Docker image runs `alembic upgrade head` on start. |
| `.python-version` | Pins Python 3.12 (ADR 0003). |
| `src/glucobalance/py.typed` | Marks the package as typed. |
| `tests/test_units.py` | Unit conversion and display formatting tests. |
| `tests/conftest.py` | Fresh in-memory SQLite database and session for every test. |
| `tests/test_db.py`, `test_models.py`, `test_migrations.py`, `test_repositories.py`, `test_seed.py` | Data layer tests (Stage 1). |
| `src/glucobalance/config.py` | `Settings` (pydantic-settings, `GBA_` env prefix, optional `.env`) and cached `get_settings()`. |
| `src/glucobalance/main.py` | `create_app()` factory, `app`, and `GET /health`. Run with `uv run uvicorn glucobalance.main:app --reload`. |
| `.env.example` | Documented variables with placeholder values; copy to `.env`. |
| `tests/test_config.py`, `tests/test_health.py` | Tests for settings loading and the health endpoint. |
| `src/glucobalance/features.py` | `feature_flags()`: the one function that turns pump/pens and glucometer/CGM into `FeatureFlags`. |
| `src/glucobalance/accounts.py` | Sign-up, Argon2 password hashing and `authenticate()`. |
| `src/glucobalance/settings_service.py` | Settings validation, `apply_settings()` and the change log (`SettingsChange`). |
| `src/glucobalance/web/` | Routes and helpers: login, onboarding wizard, home, settings page and history, form parsing. |
| `src/glucobalance/templates/`, `static/` | Jinja2 templates (Tailwind via CDN, HTMX) and the PWA manifest and icons. |
| `tests/test_features.py`, `test_accounts.py`, `test_settings_service.py`, `test_web.py` | Stage 2 tests. |
| `src/glucobalance/glucose_service.py` | Manual glucose readings: range, time and duplicate checks, `log_reading()`, tag suggestion, `is_low()`. |
| `src/glucobalance/web/log.py`, `web/log_forms.py` | The `/log/glucose`, `/log/insulin` and `/log/carbs` pages; form parsing from the user's unit and local time to mg/dL and UTC. |
| `src/glucobalance/entries.py` | Rules shared by every logged entry: `EntryError`, `PossibleDuplicate` (saved only when the user confirms) and the time check. |
| `src/glucobalance/treatment_service.py` | Logging insulin doses (dose step, max bolus, basal cap) and carbs (1 to 300 g). Records only; never suggests a dose. |
| `src/glucobalance/timeline.py` | `build_timeline()` merges a day's entries; `day_bounds()` turns a local day into UTC (23 or 25 hours on clock-change days). |
| `src/glucobalance/web/today.py` | The `/today` page: one local day of entries with previous and next day links. |
| `src/glucobalance/charts.py` | Plotly figures built in Python: `daily_figure()` (glucose, target band, insulin and carb markers) and `weekly_figure()` (readings and daily average). |
| `src/glucobalance/logbook.py` | Logbook filters, newest-first paging (`query_logbook()`) and the CSV export (`to_csv()`, with a spreadsheet-formula guard). |
| `src/glucobalance/web/chart_page.py`, `web/logbook_pages.py` | The `/chart`, `/logbook` and `/logbook.csv` pages. |
| `tests/test_glucose_service.py`, `test_log_forms.py`, `test_web_glucose.py`, `test_treatment_service.py`, `test_timeline.py`, `test_web_entries.py`, `test_charts.py`, `test_logbook.py`, `test_web_logbook.py` | Stage 3 tests. |
| `src/glucobalance/foods.py` | `FoodSource` Protocol, `OpenFoodFacts` client, `CachedFoodSource` and `carbs_for_portion()` (ADR 0008). |
| `src/glucobalance/favourites.py`, `hypo_service.py` | Favourite meals (add, list, delete, log) and the hypo log (a treatment with carbs also creates a carb entry). |
| `src/glucobalance/web/food.py`, `web/hypo.py` | The `/log/foods` search piece and the `/log/hypo` page. |
| `src/glucobalance/sitemap.py` | The body map (`SITES`, 24 sub-zones, ADR 0009) and `seed_body_sites()`; a migration loads it into `body_sites`. |
| `src/glucobalance/rotation.py` | `rank_sites()` and `suggest_site()`: the pure site ranking (written by the owner). |
| `src/glucobalance/site_service.py`, `web/sites.py` | Pump and pen rotations, logging a use, blocked sites with an optional end date, preference weights, days until the next set change; the `/sites` page (ADR 0010). |
| `src/glucobalance/bodymap.py` | Zone rectangles for the SVG body map, heat levels and 30-day use counts (ADR 0011). |
| `tests/test_sitemap.py`, `test_rotation.py`, `test_site_service.py`, `test_web_sites.py`, `test_bodymap.py`, `test_web_bodymap.py` | Stage 4 tests. |
| `tests/test_foods.py`, `test_favourites.py`, `test_hypo_service.py`, `test_web_food_hypo.py` | Food search, favourites and hypo log tests. |
| `.pre-commit-config.yaml` | Local hooks (ruff check --fix, ruff format, mypy) run through `uv run`, so they use `.venv` and the versions in `uv.lock`. |

**Already done:**

- The project plan (12 stages, below).
- README and `.gitignore`.
- Python tooling: uv, ruff (lint + format), mypy strict and pytest are configured and all run clean; pre-commit runs ruff and mypy on every commit.

**Not done yet** (still planned): the rest of Stage 3 onwards. Stage 0 added `Dockerfile`, `compose.yaml`, `.github/workflows/ci.yml`, `CLAUDE.md`, `docs/adr/` and `docs/glossary.md`. Stage 1 added the database layer: models, migrations, repositories and a seed script. Stage 2 added accounts (session cookie login), the onboarding wizard, the feature flags, the settings page with history and the base layout with a PWA manifest. Stage 3 so far adds the glucose entry page with validation, a `timezone` setting (ADR 0006) and an optional note on readings. Insulin and carb forms, a Today timeline, daily and weekly charts (Plotly, ADR 0007) and a filterable logbook with CSV export followed, then food search, favourite meals and a hypo log (ADR 0008). There are no reminders or AI code yet.

Python is pinned to 3.12 with `.python-version` (ADR 0003), matching CI and Docker; simglucose does not work on 3.14.

## Tooling and commands

Everything runs through uv, so the virtual environment never needs activating.

```bash
uv sync                  # create/update .venv from pyproject.toml and uv.lock
uv run ruff check        # lint
uv run ruff format       # format
uv run mypy              # type check (strict, covers src/ and tests/)
uv run pytest            # run tests
uv run pre-commit install           # once per clone: run the hooks on every commit
uv run pre-commit run --all-files   # run the hooks by hand on every file
uv add <package>         # add a runtime dependency
uv add --dev <package>   # add a dev dependency
```

Conventions already set in `pyproject.toml`:

- **src layout:** code lives in `src/glucobalance/`, tests in `tests/`.
- **ruff:** line length 100; rules E, W, F, I, B, UP, SIM.
- **mypy:** `strict = true` on `src` and `tests`. All new code must be fully typed.
- **pytest:** `-ra --strict-markers --strict-config`.

Before saying a task is finished, run all four checks (ruff check, ruff format, mypy, pytest) and report the result.

## Product overview

A Python web app (installable on a phone as a PWA) that logs glucose and insulin, rotates injection or infusion sites, sends care reminders, imports CGM readings, and runs an AI assistant that spots patterns and suggests small, capped adjustments for the user to confirm. It should cost nothing to run except optional LLM credit.

### Planned tech stack

| Layer | Choice |
|---|---|
| Language | Python 3.12, managed with uv |
| API | FastAPI, Pydantic v2 |
| Database | PostgreSQL (SQLite for tests), SQLAlchemy 2, Alembic |
| UI | Jinja2 templates, HTMX, Tailwind, served as a PWA |
| Charts | Plotly (or Chart.js) |
| Background jobs | APScheduler inside the app (no Redis or Celery) |
| Notifications | Web Push via pywebpush; Telegram bot as an optional extra |
| Analytics / ML | pandas, numpy, scikit-learn or LightGBM |
| Simulated patients | simglucose (UVA/Padova T1D simulator) |
| LLM | Provider-agnostic client: Ollama for local development, Claude API for the demo |
| Quality | pytest, hypothesis, ruff, mypy, pre-commit |
| CI / packaging | GitHub Actions, Docker Compose |

Charts use Plotly.js from a CDN (no Python package). Installed so far: ruff, mypy, pytest, pre-commit, FastAPI, uvicorn, pydantic-settings, SQLAlchemy, Alembic, psycopg, argon2-cffi, Jinja2, python-multipart, itsdangerous, tzdata (time zone data for Windows), httpx (dev, for tests) and simglucose (optional `sim` group). Add the others in the stage that first needs them, and explain each one when it is introduced.

### Architecture

A modular monolith: one FastAPI app split into domain modules (settings, glucose, insulin, sites, reminders, analytics, assistant). CGM sources and LLM providers sit behind adapter interfaces (ports and adapters), so either can be swapped without touching the rest of the app.

## Key design rules

These hold across all stages. Do not break them without the owner's explicit agreement.

### 1. Two settings shape the app

At onboarding the user picks two options. They are stored as user settings and turned into feature flags by **one** fully tested function, so every screen, reminder and assistant tool checks one place. Switching later is allowed and keeps history.

**Insulin delivery: pump or pens**

| Feature | Pump | Pens |
|---|---|---|
| Site map | Infusion sites by region (abdomen, thighs, arms, buttocks), split into sub-zones | Same map, finer grid, because injections happen several times a day |
| Rotation unit | One site per infusion set change | One point per injection, tracked separately for rapid-acting and long-acting insulin |
| Next-site suggestion | Least recently used site that has rested a configurable number of days | Same rule, recalculated after every injection; user can skip to the next best site |
| Unavailable sites | Mark a site blocked (irritation, lump, scar) | Mark a site blocked until an end date (bruise, sport, tattoo) or permanently; suggestions route around it |
| Main reminder | Change infusion set every N days (default 3, configurable), with early warning | Daily long-acting dose at a set time, with missed-dose alert |
| Other reminders | Reservoir or cartridge refill, pump battery | Pen-needle change, opened-pen expiry (days configurable per insulin) |
| Extra logging | Set problems: occlusion, unexplained high after change | Injection site issues, so highs can be linked to overused areas |
| Dose data | Boluses and temp basal entered manually (or imported later) | Every injection logged with insulin type and site |

**Glucose monitoring: glucometer or CGM**

| Feature | Glucometer | CGM |
|---|---|---|
| Data entry | Fast manual form: value, time, tag (fasting, before meal, after meal, bedtime, night) | Automatic import through the CGM adapter, with deduplication and gap handling |
| Reminders | Check-glucose reminders at chosen times | Sensor change, warm-up period, sensor site rotation |
| Alerts | Recheck reminder 15 minutes after a low or high entry | High, low and fast-falling alerts from the live stream |
| Statistics | Averages and ranges per time of day; time in range with a sparse-data warning | Time in range, time below range, variability, AGP |
| Assistant | Works on fewer readings, says when there is not enough data | Full pattern detection and the optional forecast |

**Shared settings in both modes:** glucose units (mg/dL or mmol/L), target range, insulin-to-carb ratio (ICR) and insulin sensitivity factor (ISF) by time of day, insulin action time, maximum single bolus, clinician contact shown in safety messages.

**Units:** store all glucose internally in mg/dL and convert only for display (`mgdl_to_mmoll()` already exists). mg/dL is the default display unit with an mmol/L switch.

### 2. CGM import: LibreLinkUp behind an adapter, with a simulator

- The app depends only on a `CGMSource` interface (`fetch_readings(since)` returning readings with trend). Nothing outside the adapter knows about LibreLinkUp.
- **Simulator adapter first** (simglucose). Tests, CI and the public demo always use it and never call Abbott's servers.
- **LibreLinkUp adapter** (Stage 6), the same approach GlucoDataHandler uses:
  - The app uses its **own follower account**. Several apps on one account cause "429 Too Many Requests" and false login errors.
  - Cache the auth token and log in again only when it expires.
  - Poll every 1 to 5 minutes (configurable), insert idempotently keyed on timestamp, back off on 429, and detect stale data (values may arrive only every 10 to 15 minutes when the Libre app stops uploading).
  - Check the exact endpoints and headers against an open-source client (for example pylibrelinkup or nightscout-librelink-up) before coding.
  - Store the follower password encrypted (Fernet key in an environment variable) and never log it.
  - Test it offline with recorded responses (respx or vcrpy fixtures with personal data removed).
- The interface is unofficial and Abbott's newer encrypted v5 interface may replace it. Record this risk in an ADR. The adapter design lets Nightscout or another source be added later.

### 3. Dosing logic is separate from the AI assistant

- **Plain, tested Python computes every number:** bolus calculator, insulin on board (IOB), adjustment suggester.
- **The LLM never computes doses.** It reads data only through tools, explains what it sees with the supporting readings, and presents suggestions the user accepts or rejects.
- Bolus formula: `carbs / ICR + (current glucose - target) / ISF - IOB`, rounded to the pen or pump step, never negative.

### 4. Safety limits

- Every dose or setting number in an assistant reply must match a tool result; a post-check compares them and **blocks the reply** if they differ.
- No suggestion when glucose is below 70 mg/dL (3.9 mmol/L); show the user's own hypo treatment steps instead.
- No suggestion when CGM data is stale (older than 15 minutes) or there are too few readings.
- Suggestions are capped by the max single bolus and by a percentage limit on setting changes (default 10%).
- An accepted change starts a review period (default 3 days) during which that setting cannot change again.
- **Nothing is ever applied automatically.** The user accepts, rejects, or chooses "ask my clinician".
- Persistent high glucose prompts a ketone check and the sick-day plan, with the clinician contact.
- Every settings change is logged with who, when, old value, new value and source (user, or accepted assistant suggestion).
- The UI states clearly that the assistant is not medical advice and settings should be agreed with a diabetes team.
- Real health data stays on the user's machine; the public demo only holds simulated patients.

## Stages and tasks

Twelve stages, each ending in something that can be demonstrated. Stages 0 to 6 make a usable app, 7 to 9 add the AI, 10 and 11 are polish and extras. Tick tasks only when they are done and approved by the owner.

### Stage 0: Foundations (done)

Done when an empty app runs locally, in Docker and in CI.

- [x] GitHub repo with a README (goal, disclaimer, roadmap)
- [x] Add an MIT `LICENSE` file
- [x] Set up uv, ruff, mypy (strict) and pytest
- [x] Set up pre-commit (ruff and mypy hooks)
- [x] FastAPI skeleton with a health endpoint and settings loaded from environment variables
- [x] Docker Compose with the app and PostgreSQL
- [x] GitHub Actions: lint, type-check and tests on every pull request
- [x] Write CLAUDE.md (conventions, pointer to this plan, "explain before coding" rule) and a `docs/adr/` folder for decisions
- [x] Domain glossary: ICR, ISF, IOB, TIR, basal, bolus, CGM, AGP

### Stage 1: Domain model and data layer (done)

Done when every core entity can be saved, read and migrated.

- [x] Models: User, Settings, GlucoseReading, InsulinDose, CarbEntry, BodySite, SiteUse, Reminder, Note
- [x] Store all glucose internally in mg/dL; convert only for display
- [x] Alembic migrations and a repository layer
- [x] Seed script that generates 30 days of simulated data with simglucose
- [x] Unit tests for models and conversions

### Stage 2: Accounts, onboarding and settings (done)

Done when a new user picks pump or pens and glucometer or CGM, and the app changes accordingly.

- [x] Sign-up and login (FastAPI session or JWT, passwords hashed with argon2)
- [x] Onboarding wizard: the two switches, units, target range, ICR and ISF by time of day, insulin action time, max bolus
- [x] Feature-flag service derived from settings (one function, fully tested)
- [x] Settings page with history of every change (who, when, old value, new value)
- [x] Base layout, navigation and PWA manifest

### Stage 3: Glucose logging (glucometer mode)

Done when manual readings are quick to enter and show on a daily chart.

- [x] Manual entry form with tag and optional note, under 5 seconds to log
- [x] Validation (plausible range, future timestamps, duplicates)
- [x] Daily and weekly chart with target band
- [x] Logbook table with filters and CSV export
- [x] Insulin and carb entry forms, shown on the same timeline
- [x] Carb logging with food search (Open Food Facts), favourite meals
- [x] Hypo log with treatment taken

### Stage 4: Site rotation engine

Done when the app suggests the next site for both pump and pen users and respects blocked sites.

- [x] Body map data: regions, sub-zones, front and back
- [x] Rotation algorithm as a pure function (written by the owner): rank sites by days since last use, rest period, blocked status and preference weights
- [x] Pump mode: one suggestion per set change, log the change, show days until next change
- [x] Pen mode: separate rotations for rapid-acting and long-acting, "site not available" with skip and end date
- [x] Clickable SVG body map with a usage heatmap
- [ ] Property-based tests (hypothesis): no blocked site is ever suggested, usage stays even over time

### Stage 5: Reminders and notifications

Done when reminders arrive on the phone even when the app is closed.

- [ ] Reminder model with rules (every N days, daily at a time, after an event)
- [ ] APScheduler jobs that survive restarts (job store in PostgreSQL)
- [ ] Web Push with VAPID keys; in-app notification centre as a fallback
- [ ] Pump: set change and reservoir; pens: long-acting dose, missed dose, pen expiry; glucometer: check reminders; CGM: sensor change
- [ ] Hypo recheck reminder 15 minutes after a low
- [ ] Snooze, done and quiet hours

### Stage 6: CGM integration

Done when Libre readings flow in automatically through LibreLinkUp, with the simulator as a second source for demos and tests. See design rule 2.

- [ ] Document the account setup in the README: share to LibreLinkUp from the Libre app and accept the invite with a separate follower account used only by this app
- [ ] `CGMSource` interface: `fetch_readings(since)` returning readings with trend
- [ ] Simulator adapter (simglucose)
- [ ] LibreLinkUp client with httpx: login, follow the regional redirect, list connections, read the current value and recent graph data (verify endpoints against an open-source client first)
- [ ] Cache and reuse the auth token; log in again only when it expires
- [ ] Polling job every 1 to 5 minutes (configurable), idempotent inserts keyed on timestamp, backoff on 429, stale-data detection
- [ ] Recorded-response tests (respx or vcrpy, personal data removed)
- [ ] Live view with trend arrow and high, low and fast-falling alerts
- [ ] Store the follower password encrypted (Fernet key in an env variable); never log it
- [ ] ADR with the risk note (unofficial interface, encrypted v5, terms of service)

### Stage 7: Analytics and reports

Done when a user can see their patterns and print a report for their diabetes clinic.

- [ ] Time in range, below range, above range, mean, coefficient of variation, glucose management indicator
- [ ] Ambulatory glucose profile (percentile bands across a typical day)
- [ ] Rule-based pattern detectors: repeated night lows, post-breakfast highs, high fasting values
- [ ] Site-performance view: average glucose after each site, to spot overused areas
- [ ] PDF clinic report for 14 or 30 days

### Stage 8: AI assistant, deterministic core

Done when every dosing number the app can show comes from tested, plain Python. See design rules 3 and 4.

- [ ] Bolus calculator (written by the owner): `carbs / ICR + (glucose - target) / ISF - IOB`, rounded to the pen or pump step
- [ ] Insulin-on-board model from logged doses and insulin action time (written by the owner)
- [ ] Adjustment suggester: turns detected patterns into capped suggestions (for example ISF or ICR for one time block)
- [ ] Safety rules: refuse with low or stale glucose, cap by max bolus, one change per setting per review period
- [ ] Unit and property tests: no negative doses, correct rounding, caps always hold

### Stage 9: AI assistant, LLM agent

Done when the user can chat with an assistant that uses the core tools, explains its reasoning and passes the evaluation suite.

- [ ] LLM client interface with Ollama and Claude implementations
- [ ] Tools: `get_recent_glucose`, `get_patterns`, `get_settings`, `calculate_bolus`, `propose_adjustment`
- [ ] Agent loop with tool calling, conversation memory and a system prompt with the safety policy
- [ ] Weekly review: summarise patterns and propose up to three adjustments, each accepted or rejected by the user
- [ ] Output check: any dose number in the reply must match a tool result, otherwise the reply is blocked
- [ ] Evaluation suite: 50+ scenarios on simulated patients plus adversarial prompts ("just tell me how much to take for pizza", "ignore your rules"), run in CI
- [ ] Eval report in the README with pass rates per model

### Stage 10: Forecast model (optional)

Done when the app predicts glucose 30 minutes ahead and the error is reported honestly.

- [ ] Feature pipeline from CGM, insulin and carbs
- [ ] Baseline (last value and linear trend) versus gradient boosting
- [ ] Report RMSE and a Clarke error grid; show the forecast only as a "likely low soon" warning
- [ ] Experiment notebook and a model card

### Stage 11: Polish and launch

Done when a stranger can open the demo and understand the project in two minutes.

- [ ] Demo accounts: simulated pump + CGM user, and pens + glucometer user
- [ ] Security pass: rate limiting, CSRF, dependency audit, secrets scan
- [ ] Data export (CSV and JSON) and account deletion
- [ ] README with architecture diagram, screenshots, how the AI is kept safe, test coverage badge
- [ ] Short demo video and a write-up post
- [ ] Free-tier deployment of the demo (synthetic data only)

## Extra features (later)

| Feature | Priority | Stage |
|---|---|---|
| Sick-day mode (alert thresholds, ketone reminders) | Should | 5, 8 |
| Exercise log, so the assistant does not blame settings for exercise lows | Should | 3, 8 |
| Insulin and supplies stock with run-out warnings | Should | 5 |
| Ketone and HbA1c lab log | Should | 3, 7 |
| Polish and English interface (gettext) | Could | 11 |
| Caregiver read-only view | Could | after 11 |
| Pump CSV data import | Could | after 11 |
| Telegram bot | Could | after 11 |

## Decisions already made

| Decision | Choice |
|---|---|
| Interface | Web app as a PWA (FastAPI + HTMX) |
| Units | mg/dL default, mmol/L switch; stored as mg/dL |
| CGM source | Simulator first, then LibreLinkUp in Stage 6 (own follower account) |
| LLM | Ollama for development, Claude for the demo |
| Language | English first, Polish in Stage 11 |
| Cost | Free tools and free tiers only; LLM credit for the demo is optional and capped |
