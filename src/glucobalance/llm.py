"""The LLM port: one small interface, two real adapters and a scripted one for tests.

The assistant (``agent.py``) only knows ``LLMClient``. Ollama (local development) and the
Claude API (the demo) are adapters behind it, so switching provider never touches the agent.
Both adapters call the providers' HTTP APIs with ``httpx``, which the app already uses, so no
vendor SDK is added. The model only ever sees the tools in ``assistant_tools``; it never gets
a database session.
"""

import json
from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

import httpx

from glucobalance.config import Settings


class LLMError(Exception):
    """The provider could not answer. The message is safe to show to the user."""


@dataclass(frozen=True, slots=True)
class ToolSpec:
    """A tool the model may call. ``parameters`` is a JSON Schema object."""

    name: str
    description: str
    parameters: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True, slots=True)
class Message:
    """One turn. ``tool`` messages carry a tool result back to the model."""

    role: Literal["user", "assistant", "tool"]
    content: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    tool_call_id: str | None = None  # set on role == "tool"
    tool_name: str | None = None  # set on role == "tool"


@dataclass(frozen=True, slots=True)
class LLMResponse:
    """Either a final ``text`` or ``tool_calls`` to run (the text may be empty then)."""

    text: str = ""
    tool_calls: tuple[ToolCall, ...] = ()


class LLMClient(Protocol):
    name: str

    def chat(
        self, system: str, messages: Sequence[Message], tools: Sequence[ToolSpec]
    ) -> LLMResponse: ...


# ---------------------------------------------------------------- Ollama


class OllamaClient:
    """Ollama's ``/api/chat`` with tool calling (a local model, nothing leaves the machine)."""

    def __init__(self, http: httpx.Client, base_url: str, model: str) -> None:
        self.http = http
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.name = f"ollama:{model}"

    def chat(
        self, system: str, messages: Sequence[Message], tools: Sequence[ToolSpec]
    ) -> LLMResponse:
        body = {
            "model": self.model,
            "stream": False,
            "messages": [{"role": "system", "content": system}, *map(_ollama_message, messages)],
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description,
                        "parameters": t.parameters,
                    },
                }
                for t in tools
            ],
            "options": {"temperature": 0},
        }
        data = _post(self.http, f"{self.base_url}/api/chat", body, {}, "Ollama")
        message = data.get("message") or {}
        calls = tuple(
            ToolCall(
                id=f"call_{i}",
                name=str(call["function"]["name"]),
                arguments=_as_arguments(call["function"].get("arguments")),
            )
            for i, call in enumerate(message.get("tool_calls") or [])
        )
        return LLMResponse(text=str(message.get("content") or ""), tool_calls=calls)


def _ollama_message(message: Message) -> dict[str, Any]:
    if message.role == "tool":
        return {"role": "tool", "content": message.content, "tool_name": message.tool_name}
    out: dict[str, Any] = {"role": message.role, "content": message.content}
    if message.tool_calls:
        out["tool_calls"] = [
            {"function": {"name": c.name, "arguments": c.arguments}} for c in message.tool_calls
        ]
    return out


# ---------------------------------------------------------------- Claude


ANTHROPIC_VERSION = "2023-06-01"
CLAUDE_MAX_TOKENS = 1024


class ClaudeClient:
    """The Anthropic Messages API with tool use."""

    def __init__(
        self,
        http: httpx.Client,
        api_key: str,
        model: str,
        base_url: str = "https://api.anthropic.com",
    ) -> None:
        self.http = http
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.name = f"claude:{model}"

    def chat(
        self, system: str, messages: Sequence[Message], tools: Sequence[ToolSpec]
    ) -> LLMResponse:
        body = {
            "model": self.model,
            "max_tokens": CLAUDE_MAX_TOKENS,
            "temperature": 0,
            "system": system,
            "messages": _claude_messages(messages),
            "tools": [
                {"name": t.name, "description": t.description, "input_schema": t.parameters}
                for t in tools
            ],
        }
        headers = {"x-api-key": self.api_key, "anthropic-version": ANTHROPIC_VERSION}
        data = _post(self.http, f"{self.base_url}/v1/messages", body, headers, "Claude")
        text: list[str] = []
        calls: list[ToolCall] = []
        for block in data.get("content") or []:
            if block.get("type") == "text":
                text.append(str(block.get("text", "")))
            elif block.get("type") == "tool_use":
                calls.append(
                    ToolCall(
                        id=str(block["id"]),
                        name=str(block["name"]),
                        arguments=_as_arguments(block.get("input")),
                    )
                )
        return LLMResponse(text="".join(text), tool_calls=tuple(calls))


def _claude_messages(messages: Sequence[Message]) -> list[dict[str, Any]]:
    """Claude wants tool results as ``tool_result`` blocks in a *user* message, all the results
    of one assistant turn together."""
    out: list[dict[str, Any]] = []
    for message in messages:
        if message.role == "tool":
            block = {
                "type": "tool_result",
                "tool_use_id": message.tool_call_id,
                "content": message.content,
            }
            last = out[-1] if out else None
            if last is not None and last["role"] == "user" and isinstance(last["content"], list):
                last["content"].append(block)
            else:
                out.append({"role": "user", "content": [block]})
        elif message.role == "assistant" and message.tool_calls:
            blocks: list[dict[str, Any]] = []
            if message.content:
                blocks.append({"type": "text", "text": message.content})
            blocks.extend(
                {"type": "tool_use", "id": c.id, "name": c.name, "input": c.arguments}
                for c in message.tool_calls
            )
            out.append({"role": "assistant", "content": blocks})
        else:
            out.append({"role": message.role, "content": message.content})
    return out


# ---------------------------------------------------------------- shared


def _post(
    http: httpx.Client, url: str, body: dict[str, Any], headers: dict[str, str], who: str
) -> dict[str, Any]:
    try:
        response = http.post(url, json=body, headers=headers, timeout=120)
    except httpx.HTTPError as error:
        raise LLMError(f"Could not reach {who}. Is it running and configured?") from error
    if response.status_code != 200:
        # Never echo the response body: it can repeat the request, and the headers hold a key.
        raise LLMError(f"{who} answered with an error (HTTP {response.status_code}).")
    try:
        data = response.json()
    except ValueError as error:
        raise LLMError(f"{who} sent an answer the app could not read.") from error
    if not isinstance(data, dict):
        raise LLMError(f"{who} sent an answer the app could not read.")
    return data


def _as_arguments(raw: Any) -> dict[str, Any]:
    """Tool arguments as a dict. Some models send them as a JSON string."""
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
        except ValueError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


# ---------------------------------------------------------------- scripted (tests, evals)


@dataclass
class ScriptedClient:
    """Answers from a fixed queue of responses, or from a function of the conversation.

    Used by the tests and by the CI evaluation suite, so the loop, the tools and the output
    check are exercised without any model. ``calls`` records what the agent sent.
    """

    responses: deque[LLMResponse | Callable[[Sequence[Message]], LLMResponse]] = field(
        default_factory=deque
    )
    name: str = "scripted"
    calls: list[tuple[str, list[Message], list[str]]] = field(default_factory=list)

    def chat(
        self, system: str, messages: Sequence[Message], tools: Sequence[ToolSpec]
    ) -> LLMResponse:
        self.calls.append((system, list(messages), [t.name for t in tools]))
        if not self.responses:
            raise LLMError("The scripted client has no more answers.")
        nxt = self.responses.popleft()
        return nxt(messages) if callable(nxt) else nxt


def build_llm(settings: Settings, http: httpx.Client) -> LLMClient | None:
    """The configured client, or None when no provider is set up (the page then says so)."""
    if settings.llm_provider == "ollama":
        return OllamaClient(http, settings.ollama_url, settings.ollama_model)
    if settings.llm_provider == "claude" and settings.anthropic_api_key:
        return ClaudeClient(http, settings.anthropic_api_key, settings.anthropic_model)
    return None
