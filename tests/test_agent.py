"""The agent loop with a scripted model: tools, memory, step limit and the output check."""

import json
from collections import deque
from datetime import timedelta

import pytest
from sqlalchemy.orm import Session

from glucobalance.agent import (
    BLOCKED_REPLY,
    MAX_STEPS,
    STEPS_REPLY,
    SYSTEM_PROMPT,
    forget,
    history,
    respond,
)
from glucobalance.llm import LLMError, LLMResponse, ScriptedClient, ToolCall
from glucobalance.models import MessageRole, User
from test_dosing_service import NOW, add_reading, user  # noqa: F401  (fixture)


def call(name: str, **arguments: object) -> LLMResponse:
    return LLMResponse(tool_calls=(ToolCall(f"id_{name}", name, dict(arguments)),))


def say(text: str) -> LLMResponse:
    return LLMResponse(text=text)


def scripted(*responses: LLMResponse) -> ScriptedClient:
    return ScriptedClient(deque(responses))


def test_a_plain_answer_is_saved_as_memory(session: Session, user: User) -> None:  # noqa: F811
    reply = respond(session, user, scripted(say("Hello!")), "  Hi  ", now=NOW)
    assert reply.text == "Hello!"
    assert not reply.blocked
    assert [(m.role, m.content) for m in history(session, user)] == [
        (MessageRole.USER, "Hi"),
        (MessageRole.ASSISTANT, "Hello!"),
    ]


def test_the_system_prompt_and_tools_are_sent(session: Session, user: User) -> None:  # noqa: F811
    client = scripted(say("ok"))
    respond(session, user, client, "Hi", now=NOW)
    system, messages, tools = client.calls[0]
    assert system.startswith(SYSTEM_PROMPT)
    assert "mg/dL" in system
    assert "14:00" in system  # the user's local time
    assert [m.content for m in messages] == ["Hi"]
    assert "calculate_bolus" in tools


def test_a_verified_dose_passes(session: Session, user: User) -> None:  # noqa: F811
    add_reading(session, user, 125)
    client = scripted(call("calculate_bolus", carbs_g=45), say("The calculator suggests 3 units."))
    reply = respond(session, user, client, "45 g of pasta", now=NOW)
    assert reply.text == "The calculator suggests 3 units."
    assert reply.called("calculate_bolus")
    # The tool result went back to the model as JSON, linked to the call.
    _, messages, _ = client.calls[1]
    assert messages[-1].role == "tool"
    assert messages[-1].tool_call_id == "id_calculate_bolus"
    assert json.loads(messages[-1].content)["units"] == 3


def test_an_invented_dose_is_blocked(session: Session, user: User) -> None:  # noqa: F811
    reply = respond(session, user, scripted(say("Take 6 units for the pizza.")), "pizza?", now=NOW)
    assert reply.blocked
    assert reply.text == BLOCKED_REPLY
    assert reply.unverified == ("6",)
    assert reply.model_text == "Take 6 units for the pizza."
    saved = history(session, user)[-1]
    assert saved.blocked
    assert saved.content == BLOCKED_REPLY  # the invented number is never stored


def test_a_changed_dose_is_blocked(session: Session, user: User) -> None:  # noqa: F811
    add_reading(session, user, 125)
    client = scripted(call("calculate_bolus", carbs_g=45), say("Make it 4 units to be safe."))
    assert respond(session, user, client, "45 g", now=NOW).blocked


def test_a_dose_from_an_earlier_turn_is_not_allowed(session: Session, user: User) -> None:  # noqa: F811
    add_reading(session, user, 125)
    respond(
        session, user, scripted(call("calculate_bolus", carbs_g=45), say("3 units.")), "x", now=NOW
    )
    reply = respond(session, user, scripted(say("Same again: 3 units.")), "again?", now=NOW)
    assert reply.blocked


def test_a_refusal_is_passed_on(session: Session, user: User) -> None:  # noqa: F811
    add_reading(session, user, 60)
    client = scripted(
        call("calculate_bolus", carbs_g=30),
        say("Your glucose is low. Treat the low first; no bolus is suggested."),
    )
    reply = respond(session, user, client, "30 g", now=NOW)
    assert not reply.blocked
    assert reply.tools[0].result["status"] == "refused"


def test_a_bad_tool_call_goes_back_as_an_error(session: Session, user: User) -> None:  # noqa: F811
    client = scripted(call("calculate_bolus", carbs_g="lots"), say("How many grams?"))
    reply = respond(session, user, client, "dinner", now=NOW)
    assert reply.tools[0].error is not None
    _, messages, _ = client.calls[1]
    assert "error" in json.loads(messages[-1].content)


def test_the_loop_stops_after_max_steps(session: Session, user: User) -> None:  # noqa: F811
    client = scripted(*[call("get_settings")] * MAX_STEPS)
    reply = respond(session, user, client, "loop", now=NOW)
    assert reply.text == STEPS_REPLY
    assert len(client.calls) == MAX_STEPS


def test_an_empty_answer_is_not_shown(session: Session, user: User) -> None:  # noqa: F811
    assert respond(session, user, scripted(say("  ")), "hm", now=NOW).text == STEPS_REPLY


def test_memory_is_sent_with_the_next_question(session: Session, user: User) -> None:  # noqa: F811
    respond(session, user, scripted(say("Hello Ann.")), "I'm Ann", now=NOW)
    client = scripted(say("You are Ann."))
    respond(session, user, client, "Who am I?", now=NOW + timedelta(minutes=1))
    _, messages, _ = client.calls[0]
    assert [(m.role, m.content) for m in messages] == [
        ("user", "I'm Ann"),
        ("assistant", "Hello Ann."),
        ("user", "Who am I?"),
    ]


def test_forget_clears_the_memory(session: Session, user: User) -> None:  # noqa: F811
    respond(session, user, scripted(say("Hi")), "Hi", now=NOW)
    forget(session, user)
    assert history(session, user) == []


def test_a_provider_error_saves_nothing(session: Session, user: User) -> None:  # noqa: F811
    with pytest.raises(LLMError):
        respond(session, user, scripted(), "Hi", now=NOW)
    assert history(session, user) == []


def test_an_empty_question_is_rejected(session: Session, user: User) -> None:  # noqa: F811
    with pytest.raises(ValueError):
        respond(session, user, scripted(say("x")), "   ", now=NOW)


def test_long_questions_are_cut(session: Session, user: User) -> None:  # noqa: F811
    respond(session, user, scripted(say("ok")), "a" * 5000, now=NOW)
    assert len(history(session, user)[0].content) == 1000


def test_the_agent_only_accepts_carbs_from_the_question(session: Session, user: User) -> None:  # noqa: F811
    add_reading(session, user, 125)
    client = scripted(call("calculate_bolus", carbs_g=30), say("How many grams?"))
    reply = respond(session, user, client, "What dose for a bowl of cereal?", now=NOW)
    assert reply.tools[0].error is not None
    assert "grams" in reply.tools[0].error
