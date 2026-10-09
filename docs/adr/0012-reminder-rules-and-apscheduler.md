# 0012. Reminder rules as pure functions, and APScheduler with a database job store

- Status: accepted
- Date: 2026-10-09

## Context

Stage 5 adds reminders: set changes, reservoirs, the daily long-acting dose, sensor changes, glucose checks and a recheck after a low. Something has to work out when each is due, hold it back during quiet hours, let the user snooze it or mark it done, and then actually fire it while nobody is looking at the app. The schedule has to survive a restart.

## Decision

- **Three rule types** (`RuleType`): every N days, daily at a time, and after an event (a fixed delay, used by the recheck after a low and the missed-dose check). A `Reminder` row holds the rule fields plus `next_due_at`, `last_done_at` and `snoozed_until`.
- **The date maths is pure** (`reminder_rules.py`): `next_daily`, `next_every_n_days`, `after_event`, `apply_quiet_hours`, `apply_snooze`. No database, no clock, and every datetime is timezone-aware. Wall-clock times are read in the user's time zone, so "08:00" stays 08:00 when the clocks change (a time in the skipped spring hour moves to just after it). "N days" means N calendar days on the user's clock, not N times 24 hours.
- **Quiet hours** (`quiet_start`, `quiet_end` on the settings, may wrap midnight) and **snooze** only ever move a due time later. The recheck after a low is marked urgent and ignores quiet hours, because a low is the one case where waiting until morning is unsafe.
- **`reminder_service` keeps the rows**: defaults per mode from `feature_flags()`, done, snooze, switch off and on, and `fire_due_reminders(session, now)`, which creates a `Notification` for each reminder whose effective time has come and sets the next due time. A daily reminder moves to tomorrow; an every-N-days reminder repeats once a day until it is marked done; an after-event reminder waits for its next event.
- **Missed long-acting dose** is two reminders working together: when the long-acting reminder fires it arms a second, after-event reminder two hours later. If a long-acting dose has been logged by then (or the first reminder was marked done), the second one stays silent.
- **APScheduler 3 inside the web process.** One interval job (`fire-reminders`, every 60 seconds, configurable) calls `run_tick`. The job store is `SQLAlchemyJobStore` on the same database engine, so the schedule is a row in `apscheduler_jobs` (created by APScheduler itself, not by Alembic) and survives restarts. `coalesce=True` and `max_instances=1` stop missed ticks from piling up or overlapping. A job is saved as a function reference, so the job is a module-level function and the session factory and push sender live in a module-level runtime object set when the scheduler is built.
- **Notifications are committed before any push is attempted**, so a failing push service cannot lose a reminder.
- **The scheduler is on by default except when `GBA_ENVIRONMENT=test`**, and can be forced either way with `GBA_SCHEDULER_ENABLED`.

## Consequences

- The rules are tested with plain values (22 tests); the service with an in-memory database and a fixed `now`.
- Polling the table every minute is simple and exact enough for reminders. It does not need one scheduled job per reminder, so there is nothing to keep in sync when a reminder is edited.
- With several app processes every one would run the job and a due reminder could fire twice. The app is a single process for now; the setting lets one process own the scheduler later.
- A reminder can be up to a minute late.
- Defaults are created when onboarding finishes, when settings are saved, and when the reminders page is opened, so accounts made before this stage get theirs too. They are not removed if the user later switches mode.

## Alternatives considered

- **Celery with Redis:** needs a broker and a worker for a few reminders. Overkill and not free to run.
- **A cron job or a separate worker container:** more to deploy, and it would not share the app's database engine in tests.
- **One APScheduler job per reminder:** would have to be updated on every edit, snooze and done. Polling one table is easier to reason about.
- **APScheduler 4:** still a pre-release.
