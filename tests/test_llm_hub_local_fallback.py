"""OllamaBackend must fall back to the bundled llama.cpp model when Ollama
is absent — this is the Chat tab's path on a machine with no Ollama installed.
Regression test for the fresh-install "Chat never responds" bug."""
from __future__ import annotations

import urllib.error
from pathlib import Path

import pytest

import backend.llm_hub as llm_hub
from backend.llm_hub import ChatMessage, ChatResult, ModelInfo, OllamaBackend
from backend.services import local_llm


@pytest.mark.asyncio
async def test_probe_offers_bundled_model_when_ollama_absent(monkeypatch):
    monkeypatch.setattr(llm_hub, "_http_get_json", lambda url: None)  # no Ollama
    monkeypatch.setattr(local_llm, "binary_path", lambda: Path("/fake/llama-server"))
    monkeypatch.setattr(local_llm, "installed_model", lambda: ("standard", Path("/fake/model.gguf")))

    r = await OllamaBackend().probe()
    assert r.online is True
    assert [m.id for m in r.models] == ["local ai"]
    assert isinstance(r.models[0], ModelInfo)


@pytest.mark.asyncio
async def test_probe_offline_when_no_ollama_and_no_bundled_model(monkeypatch):
    monkeypatch.setattr(llm_hub, "_http_get_json", lambda url: None)
    monkeypatch.setattr(local_llm, "binary_path", lambda: None)
    monkeypatch.setattr(local_llm, "installed_model", lambda: None)

    r = await OllamaBackend().probe()
    assert r.online is False


@pytest.mark.asyncio
async def test_chat_falls_back_to_bundled_on_connection_error(monkeypatch):
    def _refused(req, timeout=None):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(llm_hub.urllib.request, "urlopen", _refused)

    async def fake_bundled(self, messages, t0):
        return ChatResult(backend="ollama", model="local ai", content="hi from bundled")

    monkeypatch.setattr(OllamaBackend, "_bundled_chat", fake_bundled)

    r = await OllamaBackend().chat([ChatMessage(role="user", content="hey")], model="local ai")
    assert r.content == "hi from bundled"
    assert r.model == "local ai"


@pytest.mark.asyncio
async def test_bundled_chat_raises_when_model_missing(monkeypatch):
    monkeypatch.setattr(local_llm, "ensure_running", lambda: False)
    with pytest.raises(ConnectionError):
        await OllamaBackend()._bundled_chat([ChatMessage(role="user", content="hey")], 0.0)


@pytest.mark.asyncio
async def test_bundled_chat_uses_tight_sampling(monkeypatch):
    """llama-server's default temperature (0.8) is far too loose for the 0.5B
    fallback. The bundled path must constrain entropy itself — house style is
    NOT injected here (app.py owns it, so it reaches every backend); asserting
    its absence keeps the two from double-injecting."""
    import io
    import json as _json

    monkeypatch.setattr(local_llm, "ensure_running", lambda: True)
    captured: dict = {}

    def fake_urlopen(req, timeout=None):
        captured.update(_json.loads(req.data))
        return io.BytesIO(_json.dumps({
            "choices": [{"message": {"role": "assistant", "content": "Plain sentence."}}],
            "usage": {"total_tokens": 5},
        }).encode())

    monkeypatch.setattr(llm_hub.urllib.request, "urlopen", fake_urlopen)

    r = await OllamaBackend()._bundled_chat([ChatMessage(role="user", content="hey")], 0.0)
    assert r.content == "Plain sentence."
    assert captured["temperature"] <= 0.5
    assert captured["repeat_penalty"] >= 1.0
    assert [m["role"] for m in captured["messages"]] == ["user"]


@pytest.mark.asyncio
async def test_chat_rejects_unknown_model_instead_of_downgrading(monkeypatch):
    """Ollama 404/400s an unknown model name. HTTPError subclasses URLError, so
    this used to fall through to the bundled 0.5B and answer anyway — a silent
    quality downgrade with no error surfaced anywhere."""
    import io
    import urllib.error as _ue

    def _rejects(req, timeout=None):
        raise _ue.HTTPError(
            "http://127.0.0.1:11434/api/chat", 400, "Bad Request", {},
            io.BytesIO(b'{"error":"invalid model name"}'),
        )

    monkeypatch.setattr(llm_hub.urllib.request, "urlopen", _rejects)

    async def _must_not_run(self, messages, t0):  # pragma: no cover
        raise AssertionError("fell back to bundled model on an HTTP rejection")

    monkeypatch.setattr(OllamaBackend, "_bundled_chat", _must_not_run)

    with pytest.raises(RuntimeError, match="rejected model"):
        await OllamaBackend().chat([ChatMessage(role="user", content="hey")], model="local ai")


def test_chat_endpoint_injects_house_style_for_every_backend(monkeypatch):
    """The Chat bubble renders raw text with no markdown parser, so a model
    emitting '### Tips' puts literal hashes on screen. The endpoint pins house
    style ahead of the turn regardless of which backend serves it."""
    from fastapi.testclient import TestClient

    import backend.app as app_mod
    from backend.app import app

    captured: dict = {}

    class _FakeBackend:
        name = "ollama"

        async def chat(self, messages, model="", options=None):
            captured["messages"] = messages
            return ChatResult(backend="ollama", model=model, content="Plain sentence.")

    monkeypatch.setattr(app_mod, "get_backend", lambda name: _FakeBackend())

    with TestClient(app) as c:
        r = c.post("/api/llms/chat", json={
            "backend": "ollama", "model": "qwen3:4b",
            "messages": [{"role": "user", "content": "study tips"}],
        })
    assert r.status_code == 200

    first = captured["messages"][0]
    assert first.role == "system"
    lowered = first.content.lower()
    assert "emoji" in lowered
    assert "markdown" in lowered
