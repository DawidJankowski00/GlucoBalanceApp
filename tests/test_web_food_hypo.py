"""Food search, favourites and the hypo log, end to end through the test client."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from glucobalance.config import Settings
from glucobalance.foods import Food, FoodSearchError
from glucobalance.main import create_app
from glucobalance.models import (
    CarbEntry,
    FavouriteMeal,
    GlucoseReading,
    HypoTreatment,
    HypoTreatmentKind,
    ReadingSource,
)
from test_web import STEP1, onboard, saved_user, sign_up

WARSAW = ZoneInfo("Europe/Warsaw")


class FakeFoods:
    def __init__(self) -> None:
        self.queries: list[str] = []

    def search(self, query: str) -> list[Food]:
        self.queries.append(query)
        if query == "boom":
            raise FoodSearchError(
                "Food search is not available right now. Enter the carbs by hand."
            )
        if query == "nothing":
            return []
        return [Food("1", "Rolled oats", "Tesco", Decimal("60.5"))]


@pytest.fixture
def foods() -> FakeFoods:
    return FakeFoods()


@pytest.fixture
def client(engine: Engine, foods: FakeFoods) -> Iterator[TestClient]:
    settings = Settings(environment="test", secret_key="test-secret-key")
    with TestClient(create_app(settings, engine, food_source=foods)) as client:
        yield client


def local(minutes_ago: int = 0) -> str:
    moment = datetime.now(UTC) - timedelta(minutes=minutes_ago)
    return f"{moment.astimezone(WARSAW):%Y-%m-%dT%H:%M}"


def set_up(client: TestClient) -> None:
    sign_up(client)
    onboard(client, {**STEP1, "monitoring_mode": "glucometer", "timezone": "Europe/Warsaw"})


# ---------- food search ----------


def test_search_lists_foods_with_a_portion_form(client: TestClient, foods: FakeFoods) -> None:
    set_up(client)
    page = client.get("/log/foods?q=oats")
    assert page.status_code == 200
    assert foods.queries == ["oats"]
    assert "Rolled oats" in page.text
    assert "Tesco" in page.text
    assert "60.5 g carbs per 100 g" in page.text
    assert 'action="/log/carbs"' in page.text
    assert 'name="per100" value="60.5"' in page.text
    assert 'name="portion"' in page.text


@pytest.mark.parametrize(
    ("query", "message"),
    [
        ("a", "at least 2 letters"),
        ("", "at least 2 letters"),
        ("boom", "not available"),
        ("nothing", "No foods found"),
    ],
)
def test_search_problems_are_explained(client: TestClient, query: str, message: str) -> None:
    set_up(client)
    page = client.get(f"/log/foods?q={query}")
    assert page.status_code == 200
    assert message in page.text


def test_search_needs_login(client: TestClient) -> None:
    assert client.get("/log/foods?q=oats", follow_redirects=False).headers["location"] == "/login"


def test_the_carbs_page_has_a_search_box(client: TestClient) -> None:
    set_up(client)
    page = client.get("/log/carbs").text
    assert 'hx-get="/log/foods"' in page
    assert 'id="food-results"' in page


def test_a_chosen_food_and_portion_prefill_the_carbs_form(client: TestClient) -> None:
    set_up(client)
    page = client.get("/log/carbs?description=Rolled+oats&per100=60.5&portion=50")
    assert 'value="30.3"' in page.text
    assert 'value="Rolled oats"' in page.text


@pytest.mark.parametrize(
    "query", ["per100=abc&portion=50", "per100=60&portion=0", "per100=-1&portion=5", "portion=50"]
)
def test_a_bad_portion_is_ignored_not_an_error(client: TestClient, query: str) -> None:
    set_up(client)
    assert client.get(f"/log/carbs?description=x&{query}").status_code == 200


# ---------- favourites ----------


def test_saving_a_meal_as_a_favourite_while_logging_it(client: TestClient, engine: Engine) -> None:
    set_up(client)
    response = client.post(
        "/log/carbs",
        data={
            "grams": "45",
            "eaten_at": local(),
            "description": "with banana",
            "favourite_name": "Porridge",
        },
    )
    assert response.status_code == 200
    assert "Porridge" in response.text  # listed under favourites
    session, _ = saved_user(engine)
    with session:
        meal = session.query(FavouriteMeal).one()
        assert (meal.name, meal.grams, meal.description) == (
            "Porridge",
            Decimal("45.0"),
            "with banana",
        )
        assert session.query(CarbEntry).count() == 1


def test_a_failed_log_does_not_save_the_favourite(client: TestClient, engine: Engine) -> None:
    set_up(client)
    response = client.post(
        "/log/carbs", data={"grams": "400", "eaten_at": local(), "favourite_name": "Huge"}
    )
    assert response.status_code == 422
    session, _ = saved_user(engine)
    with session:
        assert session.query(FavouriteMeal).count() == 0


def test_a_duplicate_favourite_name_is_explained_and_the_meal_is_still_logged(
    client: TestClient, engine: Engine
) -> None:
    set_up(client)
    client.post("/log/carbs", data={"grams": "45", "eaten_at": local(60), "favourite_name": "Oats"})
    response = client.post(
        "/log/carbs", data={"grams": "30", "eaten_at": local(), "favourite_name": "oats"}
    )
    assert "already have a favourite called Oats" in response.text
    session, _ = saved_user(engine)
    with session:
        assert session.query(CarbEntry).count() == 2
        assert session.query(FavouriteMeal).count() == 1


def test_a_favourite_is_logged_in_one_tap_and_deleted(client: TestClient, engine: Engine) -> None:
    set_up(client)
    client.post("/log/carbs", data={"grams": "45", "eaten_at": local(60), "favourite_name": "Oats"})
    session, _ = saved_user(engine)
    with session:
        favourite_id = session.query(FavouriteMeal).one().id

    page = client.get("/log/carbs").text
    assert f'action="/log/favourites/{favourite_id}/log"' in page
    assert f'action="/log/favourites/{favourite_id}/delete"' in page

    logged = client.post(f"/log/favourites/{favourite_id}/log")
    assert logged.status_code == 200
    assert "Saved 45 g" in logged.text
    with session:
        assert session.query(CarbEntry).count() == 2

    deleted = client.post(f"/log/favourites/{favourite_id}/delete")
    assert deleted.status_code == 200
    with session:
        assert session.query(FavouriteMeal).count() == 0


def test_logging_a_favourite_twice_quickly_explains_the_duplicate(client: TestClient) -> None:
    set_up(client)
    client.post("/log/carbs", data={"grams": "45", "eaten_at": local(), "favourite_name": "Oats"})
    response = client.post("/log/favourites/1/log")
    assert response.status_code == 422
    assert "already logged 45 g" in response.text


def test_an_unknown_favourite_is_a_polite_error(client: TestClient) -> None:
    set_up(client)
    assert client.post("/log/favourites/999/log").status_code == 422
    assert client.post("/log/favourites/999/delete").status_code == 200


# ---------- hypo log ----------


def test_hypo_page_shows_the_form_and_the_tabs(client: TestClient) -> None:
    set_up(client)
    page = client.get("/log/hypo")
    assert page.status_code == 200
    assert 'name="treatment"' in page.text
    assert 'value="glucose_tablets"' in page.text
    assert 'name="carbs_grams"' in page.text
    assert 'href="/log/hypo"' in client.get("/log/glucose").text


def test_logging_a_hypo_treatment(client: TestClient, engine: Engine) -> None:
    set_up(client)
    client.post("/log/glucose", data={"value": "58", "measured_at": local(10)})
    response = client.post(
        "/log/hypo",
        data={"treatment": "juice", "carbs_grams": "15", "treated_at": local(), "note": "shaky"},
    )
    assert response.status_code == 200
    assert "Check your glucose again in 15 minutes" in response.text
    assert "Juice" in response.text.split("Recent treatments")[1]

    session, _ = saved_user(engine)
    with session:
        saved = session.query(HypoTreatment).one()
        assert saved.treatment is HypoTreatmentKind.JUICE
        assert saved.carbs_grams == Decimal("15.0")
        assert saved.reading is not None
        assert saved.reading.value_mgdl == 58
        assert session.query(CarbEntry).one().description == "Hypo treatment: juice"


def test_glucagon_with_carbs_is_rejected(client: TestClient, engine: Engine) -> None:
    set_up(client)
    response = client.post(
        "/log/hypo", data={"treatment": "glucagon", "carbs_grams": "15", "treated_at": local()}
    )
    assert response.status_code == 422
    assert "Glucagon has no carbs" in response.text
    session, _ = saved_user(engine)
    with session:
        assert session.query(HypoTreatment).count() == 0


def test_glucagon_asks_for_emergency_help(client: TestClient) -> None:
    set_up(client)
    response = client.post("/log/hypo", data={"treatment": "glucagon", "treated_at": local()})
    assert response.status_code == 200
    assert "emergency" in response.text.lower()


def test_a_repeated_treatment_must_be_confirmed(client: TestClient) -> None:
    set_up(client)
    data = {"treatment": "juice", "carbs_grams": "15", "treated_at": local()}
    client.post("/log/hypo", data=data)
    again = client.post("/log/hypo", data=data)
    assert again.status_code == 422
    assert 'name="confirmed"' in again.text
    assert client.post("/log/hypo", data={**data, "confirmed": "yes"}).status_code == 200


def test_bad_hypo_input_is_explained(client: TestClient) -> None:
    set_up(client)
    response = client.post("/log/hypo", data={"treatment": "cake", "treated_at": local()})
    assert response.status_code == 422
    assert "Choose what you took" in response.text
    response = client.post(
        "/log/hypo", data={"treatment": "juice", "carbs_grams": "lots", "treated_at": local()}
    )
    assert "Enter the carbs" in response.text


def test_a_low_reading_links_to_the_hypo_log(client: TestClient) -> None:
    set_up(client)
    page = client.post("/log/glucose", data={"value": "58", "measured_at": local()})
    assert 'href="/log/hypo"' in page.text


def test_hypo_log_keeps_the_reading_it_was_linked_to_in_the_logbook_data(
    client: TestClient, engine: Engine
) -> None:
    set_up(client)
    session, user = saved_user(engine)
    with session:
        session.add(
            GlucoseReading(
                user=user,
                measured_at=datetime.now(UTC) - timedelta(minutes=5),
                value_mgdl=52,
                source=ReadingSource.MANUAL,
            )
        )
        session.commit()
    client.post("/log/hypo", data={"treatment": "sweets", "treated_at": local()})
    with session:
        assert session.query(HypoTreatment).one().reading_id is not None
