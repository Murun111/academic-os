"""Resilience audit: does the app degrade gracefully when the outside world
misbehaves (bad Canvas token, no internet, no local AI, a save that fails
mid-write) instead of crashing or leaving orphaned state?

Each block targets one failure mode in one service, using the same
mocking patterns already established in that service's own test file
(RaisingClient for canvas_sync, monkeypatched httpx.AsyncClient for
websearch, an unreachable base_url for ollama).
"""
from __future__ import annotations

import httpx
import pytest

from backend.ollama import ChatMessage, OllamaService
from backend.services import websearch
from backend.services.canvas_sync import CanvasSyncService
from backend.services.courses import CoursesService
from backend.services.documents import DocumentsService


# === 1. Canvas sync error classification ===================================

class RaisingClient:
    """Fake httpx.AsyncClient that raises a given exception on the first get.
    Same shape as the one in test_canvas_sync.py."""
    def __init__(self, exc): self._exc = exc
    async def __aenter__(self): return self
    async def __aexit__(self, *a): return False
    async def get(self, url, params=None): raise self._exc


def _canvas_and_courses(tmp_path):
    canvas = CanvasSyncService(data_dir=tmp_path / "connectors")
    courses = CoursesService(data_dir=tmp_path / "courses")
    canvas.set_credentials("https://school.instructure.com", "tok_1234567890")
    return canvas, courses


@pytest.mark.asyncio
async def test_canvas_sync_401_classifies_auth_error(tmp_path, monkeypatch):
    req = httpx.Request("GET", "https://school.instructure.com/api/v1/courses")
    exc = httpx.HTTPStatusError("unauthorized", request=req,
                                 response=httpx.Response(401, request=req))
    monkeypatch.setattr("backend.services.canvas_sync.httpx.AsyncClient",
                         lambda *a, **kw: RaisingClient(exc))
    canvas, courses = _canvas_and_courses(tmp_path)
    result = await canvas.sync(courses)
    assert result["error_kind"] == "auth_error"
    assert result["errors"][0]["kind"] == "auth_error"
    assert result["error_status"] == 401


@pytest.mark.asyncio
async def test_canvas_sync_connect_error_classifies_network_error(tmp_path, monkeypatch):
    monkeypatch.setattr("backend.services.canvas_sync.httpx.AsyncClient",
                         lambda *a, **kw: RaisingClient(httpx.ConnectError("no route to host")))
    canvas, courses = _canvas_and_courses(tmp_path)
    result = await canvas.sync(courses)
    assert result["error_kind"] == "network_error"
    assert result["errors"][0]["kind"] == "network_error"
    # a connect failure carries no HTTP status
    assert "error_status" not in result


# === 2. websearch offline ====================================================

class _OfflineClient:
    """Fake httpx.AsyncClient whose get() always raises ConnectError, as if
    the machine has no route to the internet."""
    def __init__(self, *a, **kw): pass
    async def __aenter__(self): return self
    async def __aexit__(self, *a): return False
    async def get(self, url, params=None): raise httpx.ConnectError("no internet")


@pytest.mark.asyncio
async def test_websearch_search_offline_reports_offline(monkeypatch):
    monkeypatch.setattr("backend.services.websearch.httpx.AsyncClient", _OfflineClient)
    result = await websearch.search("physics homework help")
    assert result == {"error": "offline", "detail": "no internet connection"}


@pytest.mark.asyncio
async def test_websearch_fetch_offline_reports_offline(monkeypatch):
    monkeypatch.setattr("backend.services.websearch.httpx.AsyncClient", _OfflineClient)
    result = await websearch.fetch("https://example.com/article")
    assert result == {"error": "offline", "detail": "no internet connection"}


# === 3. ollama stream_chat with no server reachable =========================

@pytest.mark.asyncio
async def test_stream_chat_no_server_yields_graceful_error_not_raise(monkeypatch):
    """No Ollama, no bundled llama-server: iterating the stream must not raise
    — it should yield exactly the documented error event and stop."""
    from backend.services import local_llm
    # Make sure the bundled fallback can't kick in and mask the failure —
    # stream_chat doesn't call it today, but this keeps the test honest if
    # that ever changes.
    monkeypatch.setattr(local_llm, "installed_model", lambda: None)

    svc = OllamaService(base_url="http://127.0.0.1:1")  # nothing listens here
    events = []
    async for ev in svc.stream_chat([ChatMessage(role="user", content="hi")]):
        events.append(ev)

    assert events, "expected at least the graceful error event"
    last = events[-1]
    assert last["done"] is True
    assert "no local AI" in last["error"]
    assert last["message"]["role"] == "assistant"
    assert last["message"]["content"] == ""


# === 4. documents attach_file ordering: no orphan file on persist failure ===

def test_attach_file_leaves_no_orphan_when_jsonl_persist_fails(tmp_path, monkeypatch):
    svc = DocumentsService(data_dir=tmp_path)
    doc = svc.add(title="Transcript", kind="transcript")

    def _boom(items):
        raise OSError("disk full")

    monkeypatch.setattr(svc, "_write_all", _boom)

    with pytest.raises(OSError):
        svc.attach_file(doc.id, "transcript.pdf", b"%PDF-fake-bytes")

    # the .tmp write must have been rolled back — no leftover file of any kind
    fdir = svc._files_dir(doc.id)
    assert list(fdir.glob("*")) == []
    # and the ledger was never told about a file that doesn't exist
    assert svc.get(doc.id).files == []
