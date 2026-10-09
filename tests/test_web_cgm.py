"""The /live view and the /settings/cgm page."""

import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from glucobalance.cgm.crypto import new_key
from glucobalance.config import Settings
from glucobalance.db import make_session_factory
from glucobalance.main import create_app
from glucobalance.models import CGMConnection, CGMSourceKind, GlucoseReading, ReadingSource, Trend
from glucobalance.web.cgm import sparkline
from test_web import STEP1, onboard, saved_user, sign_up

FIXTURES = Path(__file__).parent / "fixtures" / "librelinkup"
GLOBAL = "https://api.libreview.io"
EU = "https://api-eu.libreview.io"
PATIENT = "aaaaaaaa-bbbb-cccc-dddd-000000000001"
PASSWORD = "s3cret-pass"


def fixture(name: str) -> Any:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


@pytest.fixture
def keyed(engine: Engine) -> Iterator[TestClient]:
    """An app with a CGM key and an HTTP client that respx can intercept."""
    settings = Settings(environment="test", secret_key="test-secret-key", cgm_secret_key=new_key())
    with httpx.Client() as http, TestClient(create_app(settings, engine, cgm_http=http)) as client:
        yield client


def cgm_user(client: TestClient, monitoring: str = "cgm") -> None:
    sign_up(client)
    onboard(client, {**STEP1, "monitoring_mode": monitoring})


def connection(engine: Engine) -> CGMConnection:
    session, user = saved_user(engine)
    found = session.query(CGMConnection).filter_by(user_id=user.id).one()
    session.close()
    return found


LIBRE_FORM = {
    "enabled": "on",
    "auto_accept_terms": "on",
    "email": "follower@example.com",
    "password": PASSWORD,
    "server": "io",
    "poll_minutes": "2",
}


def test_pages_need_login(client: TestClient) -> None:
    for path in ("/live", "/settings/cgm"):
        response = client.get(path, follow_redirects=False)
        assert response.headers["location"] == "/login"


def test_live_link_only_for_cgm_users(client: TestClient) -> None:
    cgm_user(client, "glucometer")
    assert 'href="/live"' not in client.get("/").text
    assert "for CGM users" in client.get("/live").text


def test_settings_page_mirrors_the_librelinkup_screen(client: TestClient) -> None:
    cgm_user(client)
    page = client.get("/settings/cgm").text
    for text in (
        "Enable",
        "Automatically accept new terms of use",
        "E-mail",
        "Password",
        "Server",
        "Default (.io)",
        "Reconnect",
        "This is not the account of the FreeStyle Libre app",
        "encrypted communication",
    ):
        assert text in page
    assert "GBA_CGM_SECRET_KEY" in page  # this app has no key configured


def test_saving_without_a_key_explains_why(client: TestClient) -> None:
    cgm_user(client)
    response = client.post("/settings/cgm", data=LIBRE_FORM)
    assert response.status_code == 422
    assert "GBA_CGM_SECRET_KEY" in response.text


def test_saving_stores_the_password_encrypted(keyed: TestClient, engine: Engine) -> None:
    cgm_user(keyed)
    response = keyed.post("/settings/cgm", data=LIBRE_FORM)
    assert response.status_code == 200
    assert "LibreLinkUp settings saved." in response.text
    assert PASSWORD not in response.text

    saved = connection(engine)
    assert saved.enabled
    assert saved.poll_minutes == 2
    assert saved.password_encrypted and PASSWORD not in saved.password_encrypted
    assert "Saved. Leave empty to keep it." in keyed.get("/settings/cgm").text


def test_an_invalid_poll_interval_is_refused(keyed: TestClient) -> None:
    cgm_user(keyed)
    response = keyed.post("/settings/cgm", data={**LIBRE_FORM, "poll_minutes": "9"})
    assert response.status_code == 422
    assert "between 1 and 5" in response.text


def test_test_connection_lists_patients_and_imports(keyed: TestClient, engine: Engine) -> None:
    cgm_user(keyed)
    keyed.post("/settings/cgm", data=LIBRE_FORM)
    with respx.mock(assert_all_called=False) as mock:
        mock.post(f"{GLOBAL}/llu/auth/login").respond(json=fixture("login_redirect"))
        mock.post(f"{EU}/llu/auth/login").respond(json=fixture("login_ok"))
        mock.get(f"{EU}/llu/connections").respond(json=fixture("connections"))
        mock.get(f"{EU}/llu/connections/{PATIENT}/graph").respond(json=fixture("graph"))
        response = keyed.post("/settings/cgm/test")

    assert response.status_code == 200
    assert "Pat Example" in response.text
    assert "Connected." in response.text
    assert connection(engine).patient_id == PATIENT


def test_test_connection_shows_a_refused_password(keyed: TestClient) -> None:
    cgm_user(keyed)
    keyed.post("/settings/cgm", data=LIBRE_FORM)
    with respx.mock() as mock:
        mock.post(f"{GLOBAL}/llu/auth/login").respond(json=fixture("login_bad_credentials"))
        response = keyed.post("/settings/cgm/test")

    assert response.status_code == 422
    assert "refused the e-mail or password" in response.text


def test_simulator_feeds_the_live_view(client: TestClient, engine: Engine) -> None:
    cgm_user(client)
    response = client.post("/settings/cgm/simulator", data={"enabled": "on"})
    assert "The simulated CGM is on." in response.text
    assert connection(engine).source is CGMSourceKind.SIMULATOR

    tested = client.post("/settings/cgm/test")
    assert "Connected." in tested.text

    live = client.get("/live").text
    assert "mg/dL" in live
    assert "<polyline" in live
    assert 'hx-get="/live/panel"' in live
    assert "mg/dL" in client.get("/live/panel").text


def test_live_view_shows_trend_low_and_stale(client: TestClient, engine: Engine) -> None:
    cgm_user(client)
    client.post("/settings/cgm/simulator", data={"enabled": "on"})
    session, user = saved_user(engine)
    now = datetime.now(UTC)
    session.add(
        GlucoseReading(
            user_id=user.id,
            measured_at=now - timedelta(minutes=2),
            value_mgdl=62,
            source=ReadingSource.SIMULATED,
            trend=Trend.FALLING_FAST,
        )
    )
    session.commit()
    session.close()

    page = client.get("/live").text
    assert "62 mg/dL" in page
    assert "↓" in page and "falling fast" in page
    assert "Treat it now" in page
    assert "No new reading" not in page

    session = make_session_factory(engine)()
    reading = session.query(GlucoseReading).one()
    reading.measured_at = now - timedelta(minutes=30)
    session.commit()
    session.close()
    assert "No new reading for more than 15 minutes" in client.get("/live").text


def test_turning_the_simulator_off_keeps_librelinkup(keyed: TestClient, engine: Engine) -> None:
    cgm_user(keyed)
    keyed.post("/settings/cgm", data=LIBRE_FORM)
    keyed.post("/settings/cgm/simulator", data={})
    saved = connection(engine)
    assert saved.source is CGMSourceKind.LIBRELINKUP
    assert saved.enabled


def test_sparkline_maps_values_into_the_box() -> None:
    start = datetime(2026, 10, 9, 15, 0, tzinfo=UTC)
    end = start + timedelta(hours=3)
    readings = [
        GlucoseReading(measured_at=start, value_mgdl=40, source=ReadingSource.CGM),
        GlucoseReading(measured_at=end, value_mgdl=400, source=ReadingSource.CGM),
    ]
    spark = sparkline(readings, start, end, low=70, high=180)
    assert spark["points"] == "0.0,80.0 300.0,0.0"  # 400 is clamped to the top
    assert spark["band_top"] == pytest.approx(36.9, abs=0.1)
