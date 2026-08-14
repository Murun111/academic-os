"""SSE chat streaming (POST /api/llms/chat/stream).

Wire contract (SHARED CONTRACTS): text/event-stream response, lines of
'data: <json>\\n\\n', event kinds:
  {"delta": "<text chunk>"}
  {"done": true, "message": <full final message obj>}
  {"error": "<friendly message>"}

Chat has two Ollama clients (llm_hub.OllamaBackend for the Chat tab,
backend/ollama.py OllamaService for essay feedback) and BOTH the direct
Ollama path and the bundled-llama fallback path inside llm_hub must stream
identically. These tests dispatch through backend.app's module-level
`get_backend` (the same name the non-streaming /api/llms/chat endpoint
already dispatches through — see test_llm_hub_local_fallback.py's
test_chat_endpoint_injects_house_style_for_every_backend for the proven
monkeypatch target) and, for the bundled-fallback case, exercise the real
backend.llm_hub.OllamaBackend with only its network edges mocked.
"""
from __future__ import annotations

import asyncio
import json

import pytest
from fastapi.testclient import TestClient

import backend.app as app_mod
import backend.llm_hub as llm_hub
from backend.app import app
from backend.llm_hub import OllamaBackend
from backend.services import local_llm


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def _parse_sse(body: str) -> list[dict]:
    """Split an SSE body into its parsed JSON event payloads."""
    events = []
    for block in body.split("\n\n"):
        block = block.strip()
        if not block:
            continue
        assert block.startswith("data: "), f"non-SSE line in body: {block!r}"
        events.append(json.loads(block[len("data: "):]))
    return events


class _FakeStreamBackend:
    """A minimal backend double whose chat_stream yields caller-supplied
    events, matching the app-wide SSE event contract shape."""

    name = "ollama"

    def __init__(self, events):
        self._events = events

    async def chat_stream(self, messages, model="", options=None):
        for ev in self._events:
            yield ev


# ── delta events + persisted final message ──────────────────────────────


def test_stream_endpoint_emits_deltas_then_done_with_persisted_message(client, monkeypatch):
    events = [
        {"delta": "Hel"},
        {"delta": "lo"},
        {"done": True, "message": {
            "role": "assistant", "content": "Hello",
            "backend": "ollama", "model": "qwen3:4b",
            "tokens": 2, "elapsed_ms": 5,
        }},
    ]
    monkeypatch.setattr(app_mod, "get_backend", lambda name: _FakeStreamBackend(events))

    with client.stream(
        "POST", "/api/llms/chat/stream",
        json={"backend": "ollama", "model": "qwen3:4b",
              "messages": [{"role": "user", "content": "hi"}]},
    ) as r:
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        body = r.read().decode()

    parsed = _parse_sse(body)
    deltas = [e["delta"] for e in parsed if "delta" in e]
    assert deltas == ["Hel", "lo"]

    done_events = [e for e in parsed if e.get("done") is True]
    assert len(done_events) == 1
    message = done_events[0]["message"]
    assert message["content"] == "Hello"
    assert message["role"] == "assistant"

    # The completed turn must be persisted to a thread (llm_hub thread store).
    threads = llm_hub.list_threads()
    assert threads, "no thread was persisted"
    newest = llm_hub.get_thread(threads[0]["id"])
    assert newest is not None
    assert newest["messages"][-2]["role"] == "user"
    assert newest["messages"][-2]["content"] == "hi"
    assert newest["messages"][-1]["role"] == "assistant"
    assert newest["messages"][-1]["content"] == "Hello"


# ── error path: single error event, never a 500 ─────────────────────────


def test_stream_endpoint_error_emits_single_error_event_no_500(client, monkeypatch):
    events = [{"error": "the model rejected this request"}]
    monkeypatch.setattr(app_mod, "get_backend", lambda name: _FakeStreamBackend(events))

    with client.stream(
        "POST", "/api/llms/chat/stream",
        json={"backend": "ollama", "model": "qwen3:4b",
              "messages": [{"role": "user", "content": "hi"}]},
    ) as r:
        assert r.status_code == 200
        body = r.read().decode()

    parsed = _parse_sse(body)
    assert len(parsed) == 1
    assert parsed[0] == {"error": "the model rejected this request"}


# ── Ollama down, bundled model available: still streams ─────────────────


async def _refused_ndjson(req, timeout):
    """Simulates Ollama being unreachable. The `yield` after the raise is
    required so Python treats this as an async generator function — the
    exception fires on the first __anext__(), before any yield executes."""
    raise ConnectionError("connection refused")
    yield  # pragma: no cover - unreachable, keeps this an async generator


async def _fake_bundled_sse_lines(req, timeout):
    yield json.dumps({"choices": [{"delta": {"content": "Hel"}}]})
    yield json.dumps({"choices": [{"delta": {"content": "lo"}}]})
    yield json.dumps({"choices": [{}], "usage": {"total_tokens": 2}})
    yield "[DONE]"


def test_ollama_backend_streams_via_bundled_fallback_when_ollama_down(monkeypatch):
    """Unit-level: backend.llm_hub.OllamaBackend.chat_stream itself, with
    only the network edges (NDJSON socket read, bundled SSE socket read,
    bundled-server readiness check) mocked. Guarantees the fallback path
    yields the same delta/done/message contract as the direct-Ollama path,
    independent of how backend.app wires it into the SSE endpoint."""
    monkeypatch.setattr(OllamaBackend, "_stream_ndjson", staticmethod(_refused_ndjson))
    monkeypatch.setattr(OllamaBackend, "_stream_sse_lines", staticmethod(_fake_bundled_sse_lines))
    monkeypatch.setattr(local_llm, "ensure_running", lambda: True)

    from backend.llm_hub import ChatMessage

    async def _collect():
        out = []
        async for ev in OllamaBackend().chat_stream(
            messages=[ChatMessage(role="user", content="hi")], model="qwen3:4b",
        ):
            out.append(ev)
        return out

    import asyncio
    events = asyncio.run(_collect())

    deltas = [e["delta"] for e in events if "delta" in e]
    assert deltas == ["Hel", "lo"]
    done_events = [e for e in events if e.get("done") is True]
    assert len(done_events) == 1
    assert done_events[0]["message"]["content"] == "Hello"
    assert not any("error" in e for e in events)


def test_stream_endpoint_still_streams_when_ollama_down_but_bundled_available(client, monkeypatch):
    """Same scenario as above, driven through the actual HTTP endpoint
    (backend="ollama") rather than a fake backend double — proves the
    endpoint really dispatches "ollama" through llm_hub.OllamaBackend
    (the Chat tab's client per CLAUDE.md), not backend/ollama.py's
    OllamaService (which has no bundled-fallback for streaming and is
    reserved for essay feedback)."""
    monkeypatch.setattr(OllamaBackend, "_stream_ndjson", staticmethod(_refused_ndjson))
    monkeypatch.setattr(OllamaBackend, "_stream_sse_lines", staticmethod(_fake_bundled_sse_lines))
    monkeypatch.setattr(local_llm, "ensure_running", lambda: True)

    with client.stream(
        "POST", "/api/llms/chat/stream",
        json={"backend": "ollama", "model": "qwen3:4b",
              "messages": [{"role": "user", "content": "hi"}]},
    ) as r:
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        body = r.read().decode()

    parsed = _parse_sse(body)
    deltas = [e["delta"] for e in parsed if "delta" in e]
    assert deltas == ["Hel", "lo"]
    done_events = [e for e in parsed if e.get("done") is True]
    assert len(done_events) == 1
    assert done_events[0]["message"]["content"] == "Hello"


# ── abort mid-stream: partial text persisted exactly once ───────────────


def test_stream_abort_mid_stream_persists_partial_text(monkeypatch):
    """Client disconnect mid-stream: the CancelledError handler in gen()
    persists the partial accumulated text exactly once and creates exactly
    one thread whose last message carries the partial content.

    Approach: drive the endpoint's StreamingResponse body_iterator manually
    (bypassing Starlette's disconnect machinery). Consume two delta events so
    full == 'Hello', then athrow(CancelledError) to hit the except handler.
    The backend's chat_stream blocks forever after the second yield so the
    outer generator cannot advance to 'done' before we inject the error.
    """

    class _BlockingBackend:
        name = "ollama"

        async def chat_stream(self, messages, model="", options=None):
            yield {"delta": "Hel"}
            yield {"delta": "lo"}
            # Suspends indefinitely; CancelledError is thrown into the outer
            # gen before this ever resolves (gen is at a yield, not here).
            await asyncio.sleep(9999)  # pragma: no cover

    monkeypatch.setattr(app_mod, "get_backend", lambda name: _BlockingBackend())

    from backend.app import llms_chat_stream

    async def _drive():
        resp = await llms_chat_stream({
            "backend": "ollama",
            "model": "qwen3:4b",
            "messages": [{"role": "user", "content": "hi"}],
        })
        agen = resp.body_iterator

        # Pull the two delta SSE lines — gen() accumulates full="Hello" and
        # suspends at its second 'yield' expression (inside the try block).
        await agen.__anext__()
        await agen.__anext__()

        # Simulate client disconnect: CancelledError is raised at gen()'s
        # current suspension point (the yield, inside the try), propagates
        # through the async-for, and is caught by the explicit handler which
        # calls _persist(full) then re-raises.
        try:
            await agen.athrow(asyncio.CancelledError)
        except (asyncio.CancelledError, StopAsyncIteration):
            pass

    asyncio.run(_drive())

    threads = llm_hub.list_threads()
    assert len(threads) == 1, f"expected exactly 1 thread, got {len(threads)}"
    thread = llm_hub.get_thread(threads[0]["id"])
    assert thread is not None
    msgs = thread["messages"]
    # save_thread appends user then assistant — both must be present.
    assert msgs[-2]["role"] == "user"
    assert msgs[-2]["content"] == "hi"
    assert msgs[-1]["role"] == "assistant"
    assert msgs[-1]["content"] == "Hello"  # "Hel" + "lo"
