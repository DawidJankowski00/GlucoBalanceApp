"""The Ollama and Claude adapters, against mocked HTTP (respx)."""

import json

import httpx
import pytest
import respx

from glucobalance.config import Settings
from glucobalance.llm import (
    ClaudeClient,
    LLMError,
    Message,
    OllamaClient,
    ToolCall,
    ToolSpec,
    build_llm,
)

TOOL = ToolSpec("get_settings", "The settings.", {"type": "object", "properties": {}})
CONVERSATION = [
    Message(role="user", content="My settings?"),
    Message(role="assistant", tool_calls=(ToolCall("t1", "get_settings", {}),)),
    Message(role="tool", content='{"icr": 10}', tool_call_id="t1", tool_name="get_settings"),
]


@respx.mock
def test_ollama_sends_tools_and_reads_tool_calls() -> None:
    route = respx.post("http://ollama:11434/api/chat").respond(
        json={
            "message": {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"function": {"name": "get_settings", "arguments": {}}}],
            }
        }
    )
    with httpx.Client() as http:
        response = OllamaClient(http, "http://ollama:11434/", "llama3.1").chat(
            "Be safe.", CONVERSATION, [TOOL]
        )
    assert response.tool_calls == (ToolCall("call_0", "get_settings", {}),)
    body = json.loads(route.calls[0].request.content)
    assert body["model"] == "llama3.1"
    assert body["stream"] is False
    assert body["messages"][0] == {"role": "system", "content": "Be safe."}
    assert body["messages"][2]["tool_calls"] == [
        {"function": {"name": "get_settings", "arguments": {}}}
    ]
    assert body["messages"][3] == {
        "role": "tool",
        "content": '{"icr": 10}',
        "tool_name": "get_settings",
    }
    assert body["tools"][0]["function"]["name"] == "get_settings"


@respx.mock
def test_ollama_reads_text_and_string_arguments() -> None:
    respx.post("http://ollama:11434/api/chat").respond(
        json={
            "message": {
                "content": "Hi",
                "tool_calls": [
                    {"function": {"name": "calculate_bolus", "arguments": '{"carbs_g": 40}'}}
                ],
            }
        }
    )
    with httpx.Client() as http:
        response = OllamaClient(http, "http://ollama:11434", "m").chat("s", [], [])
    assert response.text == "Hi"
    assert response.tool_calls[0].arguments == {"carbs_g": 40}


@respx.mock
def test_claude_sends_tool_results_as_user_blocks() -> None:
    route = respx.post("https://api.anthropic.com/v1/messages").respond(
        json={
            "content": [
                {"type": "text", "text": "Your ICR is 10 g per unit."},
            ]
        }
    )
    with httpx.Client() as http:
        response = ClaudeClient(http, "sk-test", "claude-haiku-5-5").chat(
            "Be safe.", CONVERSATION, [TOOL]
        )
    assert response.text == "Your ICR is 10 g per unit."
    assert response.tool_calls == ()
    request = route.calls[0].request
    assert request.headers["x-api-key"] == "sk-test"
    assert request.headers["anthropic-version"] == "2023-06-01"
    body = json.loads(request.content)
    assert body["system"] == "Be safe."
    assert body["tools"][0]["input_schema"] == TOOL.parameters
    assert body["messages"] == [
        {"role": "user", "content": "My settings?"},
        {
            "role": "assistant",
            "content": [{"type": "tool_use", "id": "t1", "name": "get_settings", "input": {}}],
        },
        {
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": "t1", "content": '{"icr": 10}'}],
        },
    ]


@respx.mock
def test_claude_reads_tool_use_blocks() -> None:
    respx.post("https://api.anthropic.com/v1/messages").respond(
        json={
            "content": [
                {"type": "text", "text": "Let me check."},
                {"type": "tool_use", "id": "tu_1", "name": "get_settings", "input": {}},
            ]
        }
    )
    with httpx.Client() as http:
        response = ClaudeClient(http, "k", "m").chat("s", [], [TOOL])
    assert response.text == "Let me check."
    assert response.tool_calls == (ToolCall("tu_1", "get_settings", {}),)


@respx.mock
def test_errors_never_show_the_response_body() -> None:
    respx.post("https://api.anthropic.com/v1/messages").respond(401, text="bad key sk-test")
    with httpx.Client() as http, pytest.raises(LLMError) as error:
        ClaudeClient(http, "sk-test", "m").chat("s", [], [])
    assert "HTTP 401" in str(error.value)
    assert "sk-test" not in str(error.value)


@respx.mock
def test_an_unreachable_server_is_an_llm_error() -> None:
    respx.post("http://ollama:11434/api/chat").mock(side_effect=httpx.ConnectError("down"))
    with httpx.Client() as http, pytest.raises(LLMError, match="Could not reach Ollama"):
        OllamaClient(http, "http://ollama:11434", "m").chat("s", [], [])


@respx.mock
def test_an_unreadable_answer_is_an_llm_error() -> None:
    respx.post("http://ollama:11434/api/chat").respond(text="not json")
    with httpx.Client() as http, pytest.raises(LLMError, match="could not read"):
        OllamaClient(http, "http://ollama:11434", "m").chat("s", [], [])


def test_build_llm_follows_the_settings() -> None:
    with httpx.Client() as http:
        assert build_llm(Settings(llm_provider="none"), http) is None
        assert isinstance(build_llm(Settings(llm_provider="ollama"), http), OllamaClient)
        assert build_llm(Settings(llm_provider="claude", anthropic_api_key=None), http) is None
        client = build_llm(Settings(llm_provider="claude", anthropic_api_key="k"), http)
        assert isinstance(client, ClaudeClient)
