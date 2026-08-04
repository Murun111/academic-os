"""Tests for backend.ollama. Live integration tests against the local Ollama server.

These tests REQUIRE a running `ollama serve` on the default port with the
gemma4:latest model pulled. The tests will skip (not fail) if Ollama is
unreachable, so CI in a different environment won't break — but the local
smoke check is the actual value of these tests.
"""
import json
import os
from pathlib import Path

import httpx
import pytest

from backend.ollama import ChatMessage, OllamaService, ToolCall


def _ollama_reachable() -> bool:
    """Check if Ollama is up. Used to skip integration tests when it's not."""
    try:
        r = httpx.get("http://localhost:11434/api/tags", timeout=2.0)
        return r.status_code == 200
    except (httpx.HTTPError, httpx.RequestError):
        return False


# Module-level skip — set the marker on every test in this module.
pytestmark = pytest.mark.skipif(
    not _ollama_reachable(),
    reason="Ollama not running on localhost:11434",
)


@pytest.fixture
def svc() -> OllamaService:
    """Fresh service instance per test."""
    return OllamaService()


@pytest.mark.asyncio
async def test_health_reports_model_loaded(svc: OllamaService):
    assert await svc.health() is True


@pytest.mark.asyncio
async def test_warm_model_returns_seconds(svc: OllamaService):
    """warm_model should complete in single-digit seconds on a warm machine.

    On a cold boot this can be 10-15s (model load from disk). We just check
    it's a positive number — the actual duration is logged, not asserted.
    """
    secs = await svc.warm_model()
    assert secs > 0
    assert secs < 120  # sanity: should never take this long


@pytest.mark.asyncio
async def test_chat_simple_question(svc: OllamaService):
    resp = await svc.chat([ChatMessage(role="user", content="What is 2+2? Reply with one word.")])
    assert resp.message.role == "assistant"
    assert resp.message.content.strip()
    assert resp.eval_count > 0
    assert resp.done_reason == "stop"


@pytest.mark.asyncio
async def test_chat_tool_call(svc: OllamaService):
    """Model should call the add tool when given a tool schema."""
    tools = [
        {
            "type": "function",
            "function": {
                "name": "add",
                "description": "Add two numbers",
                "parameters": {
                    "type": "object",
                    "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}},
                    "required": ["a", "b"],
                },
            },
        }
    ]
    resp = await svc.chat(
        [ChatMessage(role="user", content="Use the add tool to compute 2+3.")],
        tools=tools,
    )
    # Either the model calls the tool, or it answers in text. Both are valid
    # for an 8B model with a complex instruction. Check at least one is present.
    has_tool_call = bool(resp.message.tool_calls)
    has_text = bool(resp.message.content.strip())
    assert has_tool_call or has_text
    if has_tool_call:
        tc = resp.message.tool_calls[0]
        assert isinstance(tc, ToolCall)
        assert tc.name == "add"
        assert isinstance(tc.arguments, dict)


@pytest.mark.asyncio
async def test_stream_chat_yields_events(svc: OllamaService):
    events = []
    async for ev in svc.stream_chat([ChatMessage(role="user", content="Count to 3.")]):
        events.append(ev)
    assert len(events) >= 2  # at least one token + the final done event
    assert events[-1].get("done") is True


@pytest.mark.asyncio
async def test_message_serialization_roundtrip(svc: OllamaService):
    """Tool call message → Ollama format → back → preserves structure."""
    tc = ToolCall(id="call_1", name="foo", arguments={"x": 1})
    m = ChatMessage(role="assistant", content="", tool_calls=[tc])
    out = OllamaService._serialize_message(m)
    assert out["role"] == "assistant"
    assert out["tool_calls"][0]["function"]["name"] == "foo"
    # arguments is sent as an OBJECT (Ollama's canonical wire format); sending a
    # JSON string double-encodes and is rejected by stricter templates (qwen3).
    assert out["tool_calls"][0]["function"]["arguments"] == {"x": 1}


@pytest.mark.asyncio
async def test_close_is_idempotent(svc: OllamaService):
    """Calling close() before and after _get_client() is safe."""
    await svc.close()  # no-op (never opened)
    await svc._get_client()
    await svc.close()
    await svc.close()  # second close is a no-op
