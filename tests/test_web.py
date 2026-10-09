"""The sign-up, onboarding and settings pages, end to end through the test client."""

from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from glucobalance.db import make_session_factory
from glucobalance.models import DeliveryMode, DisplayUnit, MonitoringMode, User
from glucobalance.settings_service import history

PASSWORD = "correct horse battery"

STEP1 = {"delivery_mode": "pump", "monitoring_mode": "cgm", "display_unit": "mg/dL"}
STEP2 = {
    "target_low": "70",
    "target_high": "180",
    "insulin_action_hours": "4",
    "max_bolus_units": "10",
    "dose_step_units": "0.5",
    "clinician_contact": "Dr Kowalska 555 0100",
}
STEP3 = {
    "block_start_0": "00:00",
    "block_icr_0": "10",
    "block_isf_0": "40",
    "block_start_1": "07:00",
    "block_icr_1": "8",
    "block_isf_1": "35",
}


def sign_up(client: TestClient, email: str = "ann@example.com") -> None:
    response = client.post(
        "/signup", data={"email": email, "display_name": "Ann", "password": PASSWORD}
    )
    assert response.status_code == 200


def onboard(client: TestClient, step1: dict[str, str] | None = None) -> None:
    for step, data in ((1, step1 or STEP1), (2, STEP2), (3, STEP3)):
        response = client.post(f"/onboarding/{step}", data=data)
        assert response.status_code == 200


def saved_user(engine: Engine) -> tuple[Session, User]:
    session = make_session_factory(engine)()
    return session, session.query(User).one()


def test_anonymous_visitors_are_sent_to_login(client: TestClient) -> None:
    for path in ("/", "/settings", "/settings/history", "/onboarding/1"):
        response = client.get(path, follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == "/login"


def test_signup_logs_in_and_starts_onboarding(client: TestClient) -> None:
    sign_up(client)
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/onboarding/1"


def test_signup_errors_are_shown(client: TestClient) -> None:
    response = client.post("/signup", data={"email": "x", "display_name": "A", "password": "short"})
    assert response.status_code == 422
    assert "valid email" in response.text


def test_duplicate_signup_is_rejected(client: TestClient) -> None:
    sign_up(client)
    client.post("/logout")
    response = client.post(
        "/signup", data={"email": "ANN@example.com", "display_name": "Ann", "password": PASSWORD}
    )
    assert response.status_code == 422
    assert "already exists" in response.text


def test_login_and_logout(client: TestClient) -> None:
    sign_up(client)
    client.post("/logout")
    assert client.get("/", follow_redirects=False).headers["location"] == "/login"

    bad = client.post("/login", data={"email": "ann@example.com", "password": "wrong password"})
    assert bad.status_code == 401
    assert "Wrong email or password" in bad.text

    good = client.post("/login", data={"email": "ann@example.com", "password": PASSWORD})
    assert good.status_code == 200
    assert client.get("/", follow_redirects=False).headers["location"] == "/onboarding/1"


def test_onboarding_saves_settings_and_shows_the_home_page(
    client: TestClient, engine: Engine
) -> None:
    sign_up(client)
    onboard(client)

    home = client.get("/")
    assert home.status_code == 200
    assert "Hello, Ann" in home.text
    assert "infusion set" in home.text

    session, user = saved_user(engine)
    with session:
        assert user.settings is not None
        assert user.settings.delivery_mode is DeliveryMode.PUMP
        assert user.settings.monitoring_mode is MonitoringMode.CGM
        assert user.settings.insulin_action_minutes == 240
        assert [b.isf_mgdl for b in user.settings.time_blocks] == [40, 35]
        assert {c.source.value for c in history(session, user)} == {"onboarding"}


def test_onboarding_in_mmol_converts_to_mg_dl(client: TestClient, engine: Engine) -> None:
    sign_up(client)
    client.post("/onboarding/1", data={**STEP1, "display_unit": "mmol/L"})
    client.post("/onboarding/2", data={**STEP2, "target_low": "3.9", "target_high": "10.0"})
    client.post(
        "/onboarding/3", data={"block_start_0": "00:00", "block_icr_0": "10", "block_isf_0": "2.2"}
    )

    session, user = saved_user(engine)
    with session:
        assert user.settings is not None
        assert user.settings.display_unit is DisplayUnit.MMOLL
        assert (user.settings.target_low_mgdl, user.settings.target_high_mgdl) == (70, 180)
        assert user.settings.time_blocks[0].isf_mgdl == 40


def test_onboarding_step_errors_keep_you_on_the_step(client: TestClient) -> None:
    sign_up(client)
    client.post("/onboarding/1", data=STEP1)
    response = client.post("/onboarding/2", data={**STEP2, "target_low": "200"})
    assert response.status_code == 200
    assert "lower than the high target" in response.text
    assert 'name="target_low"' in response.text

    client.post("/onboarding/2", data=STEP2)
    response = client.post(
        "/onboarding/3", data={"block_start_0": "06:00", "block_icr_0": "10", "block_isf_0": "40"}
    )
    assert "midnight" in response.text


def test_step_one_requires_all_choices(client: TestClient) -> None:
    sign_up(client)
    response = client.post("/onboarding/1", data={"delivery_mode": "pump"})
    assert "Choose a value" in response.text


def test_finished_users_skip_onboarding(client: TestClient) -> None:
    sign_up(client)
    onboard(client)
    response = client.get("/onboarding/1", follow_redirects=False)
    assert response.headers["location"] == "/"


def test_settings_page_is_prefilled_and_saves_changes(client: TestClient, engine: Engine) -> None:
    sign_up(client)
    onboard(client)

    page = client.get("/settings")
    assert 'value="180"' in page.text

    form = {**STEP1, **STEP2, **STEP3, "target_high": "160", "delivery_mode": "pens"}
    saved = client.post("/settings", data=form)
    assert saved.status_code == 200
    assert "Settings saved" in saved.text

    session, user = saved_user(engine)
    with session:
        assert user.settings is not None
        assert user.settings.target_high_mgdl == 160
        assert user.settings.delivery_mode is DeliveryMode.PENS
        newest = history(session, user)[:2]
        assert {c.field for c in newest} == {"target_high_mgdl", "delivery_mode"}
        assert all(c.source.value == "user" for c in newest)

    page = client.get("/settings/history")
    assert "High target (mg/dL)" in page.text
    assert "Ann" in page.text


def test_invalid_settings_are_rejected_and_not_saved(client: TestClient, engine: Engine) -> None:
    sign_up(client)
    onboard(client)
    response = client.post("/settings", data={**STEP1, **STEP2, **STEP3, "max_bolus_units": "500"})
    assert response.status_code == 422
    assert "maximum bolus" in response.text

    session, user = saved_user(engine)
    with session:
        assert user.settings is not None
        assert user.settings.max_bolus_units == 10


def test_health_and_manifest_are_public(client: TestClient) -> None:
    assert client.get("/health").status_code == 200
    manifest = client.get("/static/manifest.webmanifest")
    assert manifest.status_code == 200
    assert manifest.json()["display"] == "standalone"
    assert client.get("/static/icon-192.png").headers["content-type"] == "image/png"


def test_settings_page_edits_site_rotation(client: TestClient, engine: Engine) -> None:
    sign_up(client)
    onboard(client)
    page = client.get("/settings").text
    assert 'name="site_rest_days" value="14"' in page
    assert 'name="set_change_days" value="3"' in page

    form = {**STEP1, **STEP2, **STEP3, "site_rest_days": "10", "set_change_days": "2"}
    assert client.post("/settings", data=form).status_code == 200

    session, user = saved_user(engine)
    with session:
        assert user.settings is not None
        assert (user.settings.site_rest_days, user.settings.set_change_days) == (10, 2)


def test_a_bad_rest_period_is_explained(client: TestClient) -> None:
    sign_up(client)
    onboard(client)
    response = client.post("/settings", data={**STEP1, **STEP2, **STEP3, "site_rest_days": "x"})
    assert response.status_code == 422
    assert "rest period" in response.text
