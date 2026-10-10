"""Synthetic demo accounts and the one-click demo login."""

from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from glucobalance.config import Settings
from glucobalance.db import make_session_factory
from glucobalance.demo_data import (
    PENS_EMAIL,
    PUMP_EMAIL,
    seed_demo_users,
    seed_pens_user,
    seed_pump_user,
    synthetic_pump_data,
)
from glucobalance.main import create_app
from glucobalance.models import (
    DeliveryMode,
    DoseKind,
    GlucoseReading,
    InsulinDose,
    MonitoringMode,
    ReadingSource,
    Reminder,
    User,
)

END = datetime(2026, 10, 1, 8, 30, tzinfo=UTC)


def test_pump_data_is_deterministic_and_plausible() -> None:
    first = synthetic_pump_data(7, end=END)
    assert first.readings == synthetic_pump_data(7, end=END).readings
    assert len(first.readings) == 7 * 288
    values = [v for _, v in first.readings]
    assert min(values) >= 40
    assert max(values) <= 320
    in_range = sum(70 <= v <= 180 for v in values) / len(values)
    assert 0.5 < in_range < 0.95
    assert len(first.meals) == len(first.boluses) == 7 * 3


def test_pump_user_has_the_pump_cgm_shape(session: Session) -> None:
    user = seed_pump_user(session, end=END)
    session.commit()
    assert user.settings is not None
    assert user.settings.delivery_mode is DeliveryMode.PUMP
    assert user.settings.monitoring_mode is MonitoringMode.CGM
    assert user.password_hash is None
    assert set(session.scalars(select(GlucoseReading.source))) == {ReadingSource.SIMULATED}
    assert (session.scalar(select(func.count()).select_from(Reminder)) or 0) >= 2


def test_pens_user_has_manual_readings_and_pen_doses(session: Session) -> None:
    user = seed_pens_user(session, end=END)
    session.commit()
    assert user.settings is not None
    assert user.settings.delivery_mode is DeliveryMode.PENS
    assert user.settings.monitoring_mode is MonitoringMode.GLUCOMETER
    assert set(session.scalars(select(GlucoseReading.source))) == {ReadingSource.MANUAL}
    assert set(session.scalars(select(InsulinDose.kind))) == {DoseKind.BOLUS, DoseKind.BASAL}
    assert all(r.tag is not None for r in session.scalars(select(GlucoseReading)))


def test_seeding_twice_replaces_instead_of_duplicating(session: Session) -> None:
    seed_demo_users(session, end=END)
    session.commit()
    before = session.scalar(select(func.count()).select_from(GlucoseReading))
    seed_demo_users(session, end=END)  # both exist: nothing to do
    seed_demo_users(session, end=END, replace=True)
    session.commit()
    assert session.scalar(select(func.count()).select_from(GlucoseReading)) == before
    assert {u.email for u in session.scalars(select(User))} == {PUMP_EMAIL, PENS_EMAIL}


def demo_client(engine: Engine, *, demo_mode: bool) -> TestClient:
    settings = Settings(environment="test", secret_key="test-secret-key", demo_mode=demo_mode)
    return TestClient(create_app(settings, engine))


def test_demo_login_is_off_by_default(client: TestClient) -> None:
    assert client.post("/demo/pump").status_code == 404
    assert "/demo/pump" not in client.get("/login").text


def test_demo_login_signs_in_as_each_demo_user(engine: Engine) -> None:
    with demo_client(engine, demo_mode=True) as client:
        assert "/demo/pump" in client.get("/login").text
        for kind, email in (("pump", PUMP_EMAIL), ("pens", PENS_EMAIL)):
            client.post("/logout")
            response = client.post(f"/demo/{kind}", follow_redirects=False)
            assert response.status_code == 303
            home = client.get("/")
            assert home.status_code == 200
            assert "Demo account" in home.text
            assert email in client.get("/account/export.json").text


def test_demo_pages_render_with_data(engine: Engine) -> None:
    with demo_client(engine, demo_mode=True) as client:
        client.post("/demo/pump")
        for path in ("/today", "/chart", "/analytics", "/logbook", "/sites", "/reminders", "/live"):
            assert client.get(path).status_code == 200, path
        client.post("/logout")
        client.post("/demo/pens")
        for path in ("/today", "/chart", "/analytics", "/logbook", "/sites", "/reminders"):
            assert client.get(path).status_code == 200, path


def test_demo_accounts_cannot_be_deleted(engine: Engine) -> None:
    with demo_client(engine, demo_mode=True) as client:
        client.post("/demo/pens")
        response = client.post("/account/delete", data={"confirm_email": PENS_EMAIL})
        assert response.status_code == 422
        assert "cannot be deleted" in response.text
    with make_session_factory(engine)() as session:
        assert session.scalar(select(func.count()).select_from(User)) == 2


def test_demo_users_are_rebuilt_at_startup(engine: Engine) -> None:
    with demo_client(engine, demo_mode=True):
        pass
    with make_session_factory(engine)() as session:
        assert session.scalar(select(func.count()).select_from(User)) == 2
