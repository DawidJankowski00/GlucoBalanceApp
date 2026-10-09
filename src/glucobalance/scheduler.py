"""The background jobs: due reminders, and CGM polling with live alerts.

APScheduler runs two jobs inside the web process: ``fire_reminders_job`` turns due reminders
into notifications and phone pushes, and ``poll_cgm_job`` fetches new CGM readings for every
connection that is due and raises live alerts. Its
job store is the database, so the schedule is kept in a table (``apscheduler_jobs``) and a
restart picks it up again instead of starting from nothing.

The store saves a job as a reference to a function plus its arguments, and an engine or a
sender cannot be saved that way. So each job is a plain module-level function and the things
it needs live in ``_runtime``, set when the scheduler is built.
"""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from glucobalance.cgm_service import CGMRuntime, poll_due
from glucobalance.config import Settings
from glucobalance.push import PushSender, deliver
from glucobalance.reminder_service import fire_due_reminders

log = logging.getLogger(__name__)

JOB_ID = "fire-reminders"
CGM_JOB_ID = "poll-cgm"
# A tick that could not run on time (the app was down) still runs if it is at most this late.
MISFIRE_GRACE_SECONDS = 300


@dataclass(frozen=True, slots=True)
class _Runtime:
    session_factory: sessionmaker[Session]
    sender: PushSender | None
    cgm: CGMRuntime | None


_runtime: _Runtime | None = None


def run_tick(
    session_factory: sessionmaker[Session], sender: PushSender | None, *, now: datetime
) -> int:
    """Fire what is due, save the notifications, then push them. Returns how many were fired.

    The notifications are committed *before* any push is attempted, so a slow or failing push
    service can never lose a reminder.
    """
    with session_factory() as session:
        created = fire_due_reminders(session, now=now)
        session.commit()
        if created:
            deliver(session, created, sender)
            session.commit()  # removes subscriptions the push service reported as gone
        return len(created)


def fire_reminders_job() -> None:
    """The scheduled job. Does nothing until ``build_scheduler`` has set up the runtime."""
    if _runtime is None:
        log.warning("Reminder job ran before the scheduler was set up")
        return
    run_tick(_runtime.session_factory, _runtime.sender, now=datetime.now(UTC))


def run_cgm_tick(
    session_factory: sessionmaker[Session],
    sender: PushSender | None,
    runtime: CGMRuntime,
    *,
    now: datetime,
) -> int:
    """Poll the CGM connections that are due, save readings and alerts, then push the alerts."""
    with session_factory() as session:
        created = poll_due(session, runtime, now=now)
        session.commit()
        if created:
            deliver(session, created, sender)
            session.commit()
        return len(created)


def poll_cgm_job() -> None:
    """The scheduled CGM job. Does nothing until ``build_scheduler`` has set up the runtime."""
    if _runtime is None or _runtime.cgm is None:
        log.warning("CGM job ran before the scheduler was set up")
        return
    run_cgm_tick(_runtime.session_factory, _runtime.sender, _runtime.cgm, now=datetime.now(UTC))


def build_scheduler(
    settings: Settings,
    engine: Engine,
    session_factory: sessionmaker[Session],
    sender: PushSender | None,
    cgm: CGMRuntime | None = None,
) -> BackgroundScheduler:
    """A scheduler with the reminder job (and the CGM job), stored in the database.

    Not started yet. Each CGM connection has its own 1 to 5 minute interval; the job only
    checks every ``cgm_tick_seconds`` which of them are due.
    """
    global _runtime
    _runtime = _Runtime(session_factory, sender, cgm)
    scheduler = BackgroundScheduler(
        jobstores={"default": SQLAlchemyJobStore(engine=engine)},
        timezone=UTC,
        job_defaults={
            "coalesce": True,  # several missed ticks run once, not several times
            "max_instances": 1,  # never two ticks at the same time
            "misfire_grace_time": MISFIRE_GRACE_SECONDS,
        },
    )
    scheduler.add_job(
        fire_reminders_job,
        "interval",
        seconds=settings.reminder_poll_seconds,
        id=JOB_ID,
        replace_existing=True,
    )
    if cgm is not None:
        scheduler.add_job(
            poll_cgm_job,
            "interval",
            seconds=settings.cgm_tick_seconds,
            id=CGM_JOB_ID,
            replace_existing=True,
        )
    return scheduler
