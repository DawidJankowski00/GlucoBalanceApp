"""The scheduler: one job that fires due reminders, kept in the database across restarts."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from glucobalance.accounts import register
from glucobalance.config import Settings
from glucobalance.db import make_engine, make_session_factory
from glucobalance.models import (
    DeliveryMode,
    MonitoringMode,
    Notification,
    UserSettings,
)
from glucobalance.push import PushPayload, PushTarget, subscribe
from glucobalance.reminder_service import ensure_default_reminders
from glucobalance.scheduler import JOB_ID, build_scheduler, run_tick

NOW = datetime(2026, 10, 9, 10, 0, tzinfo=UTC)


class RecordingSender:
    def __init__(self) -> None:
        self.sent: list[PushPayload] = []

    def send(self, target: PushTarget, payload: PushPayload) -> None:
        self.sent.append(payload)


def user_with_phone(session: Session) -> None:
    user = register(session, "ann@example.com", "Ann", "correct horse battery")
    session.add(
        UserSettings(
            user=user,
            delivery_mode=DeliveryMode.PUMP,
            monitoring_mode=MonitoringMode.CGM,
            max_bolus_units=Decimal("10"),
            timezone="UTC",
        )
    )
    session.flush()
    ensure_default_reminders(session, user, now=NOW)
    subscribe(session, user, endpoint="https://push.example/a", p256dh="k", auth="a", now=NOW)
    session.commit()


def test_a_tick_saves_notifications_and_pushes_them(engine: Engine) -> None:
    factory = make_session_factory(engine)
    with factory() as session:
        user_with_phone(session)
    sender = RecordingSender()

    run_tick(factory, sender, now=NOW + timedelta(days=15, hours=1))

    with factory() as session:
        titles = {n.title for n in session.query(Notification).all()}
    assert titles == {"Change infusion set", "Check pump reservoir", "Change CGM sensor"}
    assert len(sender.sent) == 3


def test_a_tick_with_nothing_due_does_nothing(engine: Engine) -> None:
    factory = make_session_factory(engine)
    with factory() as session:
        user_with_phone(session)
    sender = RecordingSender()
    run_tick(factory, sender, now=NOW + timedelta(minutes=5))
    assert sender.sent == []


def test_a_push_failure_does_not_lose_the_notification(engine: Engine) -> None:
    class Broken:
        def send(self, target: PushTarget, payload: PushPayload) -> None:
            raise RuntimeError("down")

    factory = make_session_factory(engine)
    with factory() as session:
        user_with_phone(session)
    run_tick(factory, Broken(), now=NOW + timedelta(days=15, hours=1))
    with factory() as session:
        assert session.query(Notification).count() == 3


def test_the_job_is_registered_once_and_survives_a_restart(tmp_path: Path) -> None:
    engine = make_engine(f"sqlite:///{tmp_path / 'jobs.db'}")
    factory = make_session_factory(engine)
    settings = Settings(environment="test", reminder_poll_seconds=60)

    first = build_scheduler(settings, engine, factory, None)
    first.start(paused=True)
    job = first.get_job(JOB_ID)
    assert job is not None
    assert job.trigger.interval == timedelta(seconds=60)
    first.shutdown()

    # A new scheduler object (the app restarted) finds the job in the database.
    second = BackgroundScheduler()
    from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore

    second.add_jobstore(SQLAlchemyJobStore(engine=engine), "default")
    second.start(paused=True)
    assert second.get_job(JOB_ID) is not None
    second.shutdown()

    # Building it again replaces the job instead of adding a second one.
    third = build_scheduler(settings, engine, factory, None)
    third.start(paused=True)
    assert [j.id for j in third.get_jobs()] == [JOB_ID]  # no CGM runtime, no CGM job
    third.shutdown()
    engine.dispose()


def test_the_app_starts_the_scheduler_only_when_asked(engine: Engine) -> None:
    from fastapi.testclient import TestClient

    from glucobalance.main import create_app

    off = create_app(Settings(environment="test", secret_key="k"), engine)
    with TestClient(off):
        assert off.state.scheduler is None

    on = create_app(Settings(environment="test", secret_key="k", scheduler_enabled=True), engine)
    with TestClient(on):
        assert on.state.scheduler is not None
        assert on.state.scheduler.running
    assert not on.state.scheduler.running


def test_the_cgm_job_is_added_with_a_runtime(tmp_path: Path) -> None:
    import httpx

    from glucobalance.cgm_service import CGMRuntime
    from glucobalance.scheduler import CGM_JOB_ID

    engine = make_engine(f"sqlite:///{tmp_path / 'jobs.db'}")
    settings = Settings(environment="test", cgm_tick_seconds=30)
    with httpx.Client() as http:
        runtime = CGMRuntime(http=http, box=None, trace=lambda: [100])
        scheduler = build_scheduler(settings, engine, make_session_factory(engine), None, runtime)
        scheduler.start(paused=True)
        job = scheduler.get_job(CGM_JOB_ID)
        assert job is not None
        assert job.trigger.interval == timedelta(seconds=30)
        scheduler.shutdown()
    engine.dispose()


def test_a_cgm_tick_imports_readings_and_pushes_a_low_alert(engine: Engine) -> None:
    import httpx

    from glucobalance.cgm_service import CGMRuntime, use_simulator
    from glucobalance.models import GlucoseReading, User
    from glucobalance.scheduler import run_cgm_tick

    factory = make_session_factory(engine)
    with factory() as session:
        user_with_phone(session)
        user = session.query(User).one()
        use_simulator(session, user, enabled=True)
        session.commit()
    sender = RecordingSender()

    with httpx.Client() as http:
        runtime = CGMRuntime(http=http, box=None, trace=lambda: [55])
        assert run_cgm_tick(factory, sender, runtime, now=NOW) == 1

    with factory() as session:
        assert session.query(GlucoseReading).count() > 0
    assert [p.title for p in sender.sent] == ["Low glucose"]
