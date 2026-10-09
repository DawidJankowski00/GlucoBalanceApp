"""The glucose logging page, end to end through the test client."""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient
from sqlalchemy import Engine

from glucobalance.models import GlucoseReading, GlucoseTag, ReadingSource
from test_web import STEP1, onboard, saved_user, sign_up

WARSAW = ZoneInfo("Europe/Warsaw")


def local(minutes_ago: int = 0) -> str:
    """A datetime-local form value, the way the browser sends it."""
    moment = datetime.now(UTC) - timedelta(minutes=minutes_ago)
    return f"{moment.astimezone(WARSAW):%Y-%m-%dT%H:%M}"


def set_up(client: TestClient, **step1: str) -> None:
    sign_up(client)
    onboard(
        client, {**STEP1, "monitoring_mode": "glucometer", "timezone": "Europe/Warsaw", **step1}
    )


def test_onboarding_stores_the_browser_timezone(client: TestClient, engine: Engine) -> None:
    set_up(client)
    session, user = saved_user(engine)
    with session:
        assert user.settings is not None
        assert user.settings.timezone == "Europe/Warsaw"


def test_unknown_browser_timezone_falls_back_to_utc(client: TestClient, engine: Engine) -> None:
    set_up(client, timezone="Nowhere/Special")
    session, user = saved_user(engine)
    with session:
        assert user.settings is not None
        assert user.settings.timezone == "UTC"


def test_settings_page_edits_the_timezone(client: TestClient, engine: Engine) -> None:
    set_up(client)
    page = client.get("/settings")
    assert 'value="Europe/Warsaw"' in page.text


def test_log_page_needs_login_and_settings(client: TestClient) -> None:
    assert client.get("/log/glucose", follow_redirects=False).headers["location"] == "/login"
    sign_up(client)
    assert client.get("/log/glucose", follow_redirects=False).headers["location"] == (
        "/onboarding/1"
    )


def test_log_page_is_prefilled_with_the_local_time(client: TestClient) -> None:
    set_up(client)
    page = client.get("/log/glucose")
    assert page.status_code == 200
    assert 'name="value"' in page.text
    assert "autofocus" in page.text
    assert f'value="{local()[:13]}' in page.text  # same local date and hour
    assert "mg/dL" in page.text


def test_logging_a_reading_saves_it_and_lists_it(client: TestClient, engine: Engine) -> None:
    set_up(client)
    response = client.post(
        "/log/glucose",
        data={"value": "126", "measured_at": local(), "tag": "before_meal", "note": "walk"},
    )
    assert response.status_code == 200
    assert "Saved 126 mg/dL" in response.text
    assert "126 mg/dL" in response.text.split("Recent readings")[1]

    session, _ = saved_user(engine)
    with session:
        reading = session.query(GlucoseReading).one()
        assert reading.value_mgdl == 126
        assert reading.source is ReadingSource.MANUAL
        assert reading.tag is GlucoseTag.BEFORE_MEAL
        assert reading.note == "walk"


def test_mmol_users_type_and_see_mmol(client: TestClient, engine: Engine) -> None:
    sign_up(client)
    client.post(
        "/onboarding/1",
        data={**STEP1, "display_unit": "mmol/L", "timezone": "Europe/Warsaw"},
    )
    client.post(
        "/onboarding/2",
        data={
            "target_low": "3.9",
            "target_high": "10.0",
            "insulin_action_hours": "4",
            "max_bolus_units": "10",
            "dose_step_units": "0.5",
        },
    )
    client.post(
        "/onboarding/3", data={"block_start_0": "00:00", "block_icr_0": "10", "block_isf_0": "2.2"}
    )
    response = client.post("/log/glucose", data={"value": "6,2", "measured_at": local()})
    assert "Saved 6.2 mmol/L" in response.text

    session, _ = saved_user(engine)
    with session:
        assert session.query(GlucoseReading).one().value_mgdl == 112


def test_invalid_reading_shows_the_error_and_keeps_the_input(
    client: TestClient, engine: Engine
) -> None:
    set_up(client)
    response = client.post("/log/glucose", data={"value": "900", "measured_at": local()})
    assert response.status_code == 422
    assert "between 20 and 600 mg/dL" in response.text
    assert 'value="900"' in response.text

    session, _ = saved_user(engine)
    with session:
        assert session.query(GlucoseReading).count() == 0


def test_double_tap_is_rejected(client: TestClient) -> None:
    set_up(client)
    client.post("/log/glucose", data={"value": "140", "measured_at": local(3)})
    response = client.post("/log/glucose", data={"value": "140", "measured_at": local()})
    assert response.status_code == 422
    assert "same value" in response.text


def test_a_low_reading_shows_hypo_steps(client: TestClient) -> None:
    set_up(client)
    response = client.post("/log/glucose", data={"value": "58", "measured_at": local()})
    assert response.status_code == 200
    assert "Low glucose" in response.text
    assert "15 g of fast-acting carbohydrate" in response.text
    assert "Dr Kowalska" in response.text  # clinician contact from onboarding


def test_cgm_users_can_add_a_fingerstick(client: TestClient) -> None:
    sign_up(client)
    onboard(client)  # pump + CGM
    page = client.get("/log/glucose")
    assert page.status_code == 200
    assert "fingerstick" in page.text


def test_navigation_links_to_the_log(client: TestClient) -> None:
    set_up(client)
    assert 'href="/log/glucose"' in client.get("/").text
