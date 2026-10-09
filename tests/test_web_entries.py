"""The insulin and carb forms and the Today timeline, end to end through the test client."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient
from sqlalchemy import Engine

from glucobalance.models import CarbEntry, DoseKind, InsulinDose, InsulinType
from test_web import STEP1, onboard, saved_user, sign_up

WARSAW = ZoneInfo("Europe/Warsaw")


def local(minutes_ago: int = 0) -> str:
    moment = datetime.now(UTC) - timedelta(minutes=minutes_ago)
    return f"{moment.astimezone(WARSAW):%Y-%m-%dT%H:%M}"


def set_up(client: TestClient, delivery: str = "pens") -> None:
    sign_up(client)
    onboard(
        client,
        {
            **STEP1,
            "delivery_mode": delivery,
            "monitoring_mode": "glucometer",
            "timezone": "Europe/Warsaw",
        },
    )


def dose(**values: str) -> dict[str, str]:
    return {"units": "4", "insulin_type": "rapid", "kind": "bolus", "taken_at": local(), **values}


# ---------- insulin ----------


def test_insulin_page_shows_the_form(client: TestClient) -> None:
    set_up(client)
    page = client.get("/log/insulin")
    assert page.status_code == 200
    assert 'name="units"' in page.text
    assert "steps of 0.5" in page.text
    assert 'value="long"' in page.text  # pens have long-acting insulin


def test_pump_users_only_log_rapid_acting(client: TestClient) -> None:
    set_up(client, delivery="pump")
    assert 'value="long"' not in client.get("/log/insulin").text


def test_logging_a_dose_saves_it(client: TestClient, engine: Engine) -> None:
    set_up(client)
    response = client.post("/log/insulin", data=dose(units="4.5"))
    assert response.status_code == 200
    assert "Saved 4.5 units" in response.text

    session, _ = saved_user(engine)
    with session:
        saved = session.query(InsulinDose).one()
        assert saved.units == Decimal("4.5")
        assert (saved.kind, saved.insulin_type) == (DoseKind.BOLUS, InsulinType.RAPID)


def test_a_dose_above_the_max_bolus_is_rejected(client: TestClient, engine: Engine) -> None:
    set_up(client)
    response = client.post("/log/insulin", data=dose(units="12"))
    assert response.status_code == 422
    assert "maximum bolus of 10 units" in response.text
    assert 'value="12"' in response.text
    session, _ = saved_user(engine)
    with session:
        assert session.query(InsulinDose).count() == 0


def test_a_repeated_dose_must_be_confirmed(client: TestClient, engine: Engine) -> None:
    set_up(client)
    client.post("/log/insulin", data=dose(taken_at=local(5)))
    response = client.post("/log/insulin", data=dose())
    assert response.status_code == 422
    assert "already logged 4 units" in response.text
    assert 'name="confirmed"' in response.text

    confirmed = client.post("/log/insulin", data=dose(confirmed="yes"))
    assert confirmed.status_code == 200
    session, _ = saved_user(engine)
    with session:
        assert session.query(InsulinDose).count() == 2


# ---------- carbs ----------


def test_logging_carbs_saves_them(client: TestClient, engine: Engine) -> None:
    set_up(client)
    page = client.get("/log/carbs")
    assert 'name="grams"' in page.text

    response = client.post(
        "/log/carbs", data={"grams": "45", "eaten_at": local(), "description": "porridge"}
    )
    assert response.status_code == 200
    assert "Saved 45 g" in response.text
    session, _ = saved_user(engine)
    with session:
        saved = session.query(CarbEntry).one()
        assert (saved.grams, saved.description) == (Decimal("45.0"), "porridge")


def test_invalid_carbs_are_rejected(client: TestClient) -> None:
    set_up(client)
    response = client.post("/log/carbs", data={"grams": "400", "eaten_at": local()})
    assert response.status_code == 422
    assert "between 1 and 300 g" in response.text


# ---------- today ----------


def test_today_lists_every_entry_in_local_time_order(client: TestClient) -> None:
    set_up(client)
    client.post("/log/glucose", data={"value": "142", "measured_at": local(30)})
    client.post("/log/carbs", data={"grams": "45", "eaten_at": local(20), "description": "toast"})
    client.post("/log/insulin", data=dose(taken_at=local(19)))

    page = client.get("/today")
    assert page.status_code == 200
    text = page.text
    positions = [text.index("142 mg/dL"), text.index("45 g"), text.index("4 units")]
    assert positions == sorted(positions)
    assert "toast" in text
    assert local(30)[11:] in text  # shown as local HH:MM


def test_today_can_show_another_day(client: TestClient) -> None:
    set_up(client)
    client.post("/log/glucose", data={"value": "142", "measured_at": local()})
    yesterday = (datetime.now(UTC).astimezone(WARSAW) - timedelta(days=1)).date()
    page = client.get(f"/today?day={yesterday.isoformat()}")
    assert page.status_code == 200
    assert "142 mg/dL" not in page.text
    assert "Nothing logged" in page.text


def test_a_bad_day_falls_back_to_today(client: TestClient) -> None:
    set_up(client)
    assert client.get("/today?day=not-a-date").status_code == 200


def test_navigation_links_to_today_and_the_forms(client: TestClient) -> None:
    set_up(client)
    home = client.get("/").text
    assert 'href="/today"' in home
    page = client.get("/log/glucose").text
    assert 'href="/log/insulin"' in page
    assert 'href="/log/carbs"' in page
