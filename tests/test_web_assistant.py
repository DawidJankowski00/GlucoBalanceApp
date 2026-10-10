"""The assistant chat and the weekly review page, through the test client."""

import json
from collections import deque
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, update

from glucobalance.agent import BLOCKED_REPLY
from glucobalance.config import Settings
from glucobalance.llm import LLMResponse, ScriptedClient, ToolCall
from glucobalance.main import create_app
from glucobalance.models import (
    GlucoseReading,
    ReadingSource,
    SettingsChange,
    StoredSuggestion,
    SuggestionStatus,
)
from test_web import onboard, saved_user, sign_up


@pytest.fixture
def llm() -> ScriptedClient:
    return ScriptedClient(deque())


@pytest.fixture
def chat(engine: Engine, llm: ScriptedClient) -> Iterator[TestClient]:
    settings = Settings(environment="test", secret_key="test-secret-key")
    with TestClient(create_app(settings, engine, llm=llm)) as client:
        sign_up(client)
        onboard(client)
        yield client


def add_reading(engine: Engine, value: int, minutes_ago: int = 5) -> None:
    session, user = saved_user(engine)
    with session:
        session.add(
            GlucoseReading(
                user=user,
                measured_at=datetime.now(UTC) - timedelta(minutes=minutes_ago),
                value_mgdl=value,
                source=ReadingSource.CGM,
            )
        )
        session.commit()


def test_pages_need_login(client: TestClient) -> None:
    for path in ("/assistant", "/assistant/review"):
        assert client.get(path, follow_redirects=False).status_code == 303


def test_without_a_provider_the_page_says_so(client: TestClient) -> None:
    sign_up(client)
    onboard(client)
    page = client.get("/assistant").text
    assert "not set up on this server" in page
    assert "not medical advice" in page
    response = client.post("/assistant", data={"question": "hi"})
    assert "not set up on this server" in response.text


def test_a_question_and_answer_are_shown(chat: TestClient, llm: ScriptedClient) -> None:
    llm.responses.append(LLMResponse(text="Hello Ann."))
    page = chat.post("/assistant", data={"question": "Hi there"}).text
    assert "Hi there" in page
    assert "Hello Ann." in page
    assert "Model: scripted" in page


def test_a_verified_dose_is_shown(chat: TestClient, llm: ScriptedClient, engine: Engine) -> None:
    add_reading(engine, 125)
    llm.responses.extend(
        [
            LLMResponse(tool_calls=(ToolCall("c1", "calculate_bolus", {"carbs_g": 40}),)),
            lambda messages: LLMResponse(
                text=f"The calculator suggests {_units(messages[-1].content)} units."
            ),
        ]
    )
    page = chat.post("/assistant", data={"question": "40 g of rice"}).text
    assert "The calculator suggests" in page
    assert "blocked by the safety check" not in page


def _units(content: str) -> str:
    return str(json.loads(content)["units"])


def test_an_invented_dose_is_blocked_on_the_page(chat: TestClient, llm: ScriptedClient) -> None:
    llm.responses.append(LLMResponse(text="Just take 8 units for the pizza."))
    page = chat.post("/assistant", data={"question": "pizza"}).text
    assert "8 units" not in page
    assert BLOCKED_REPLY.replace("'", "&#39;") in page
    assert "blocked by the safety check" in page


def test_a_provider_error_is_shown_and_nothing_saved(chat: TestClient) -> None:
    page = chat.post("/assistant", data={"question": "Hi"}).text  # the script is empty
    assert "no more answers" in page
    assert "Clear conversation" not in page


def test_clearing_the_conversation(chat: TestClient, llm: ScriptedClient) -> None:
    llm.responses.append(LLMResponse(text="Hello."))
    chat.post("/assistant", data={"question": "Hi"})
    page = chat.post("/assistant/clear").text
    assert "Conversation cleared." in page
    assert "Hello." not in page


def add_night_lows(engine: Engine) -> None:
    session, user = saved_user(engine)
    with session:
        # Onboarding was "two months ago", so the settings are not frozen by the 7-day rule.
        session.execute(
            update(SettingsChange).values(changed_at=datetime.now(UTC) - timedelta(days=60))
        )
        today = datetime.now(UTC).replace(hour=1, minute=0, second=0, microsecond=0)
        for day in range(1, 5):
            session.add(
                GlucoseReading(
                    user=user,
                    measured_at=today - timedelta(days=day),
                    value_mgdl=60,
                    source=ReadingSource.CGM,
                )
            )
        session.commit()


def test_review_page_without_data(chat: TestClient) -> None:
    page = chat.get("/assistant/review").text
    assert "No glucose readings in the last two weeks" in page
    assert "Nothing waiting" in page


def test_running_the_review_and_accepting(chat: TestClient, engine: Engine) -> None:
    add_night_lows(engine)
    page = chat.post("/assistant/review").text
    assert "Review done: 1 suggestion to decide on." in page
    assert "Repeated night lows" in page
    assert "Sensitivity (ISF) from 00:00: 40 mg/dL per unit to 44 mg/dL per unit" in page

    session, _ = saved_user(engine)
    with session:
        row = session.query(StoredSuggestion).one()
    page = chat.post(f"/assistant/suggestions/{row.id}/accept").text
    assert "Change saved" in page
    assert "Accepted: Sensitivity (ISF)" in page
    history = chat.get("/settings/history").text
    assert "assistant" in history.lower()


def test_rejecting_a_suggestion(chat: TestClient, engine: Engine) -> None:
    add_night_lows(engine)
    chat.post("/assistant/review")
    session, _ = saved_user(engine)
    with session:
        row = session.query(StoredSuggestion).one()
    page = chat.post(f"/assistant/suggestions/{row.id}/reject").text
    assert "Nothing changed" in page
    session, _ = saved_user(engine)
    with session:
        assert session.get(StoredSuggestion, row.id).status is SuggestionStatus.REJECTED  # type: ignore[union-attr]


def test_deciding_twice_shows_the_reason(chat: TestClient, engine: Engine) -> None:
    add_night_lows(engine)
    chat.post("/assistant/review")
    session, _ = saved_user(engine)
    with session:
        row = session.query(StoredSuggestion).one()
    chat.post(f"/assistant/suggestions/{row.id}/reject")
    page = chat.post(f"/assistant/suggestions/{row.id}/accept").text
    assert "already been decided" in page


def test_the_nav_links_to_the_assistant(chat: TestClient) -> None:
    assert 'href="/assistant"' in chat.get("/").text
