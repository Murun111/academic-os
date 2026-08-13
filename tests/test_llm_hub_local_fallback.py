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
async def test_bundled_chat_injects_house_style_and_tight_sampling(monkeypatch):
    """The bundled (esp. 0.5B) model drifts into emoji/hashtag voice on bare
    turns with default sampling — the fallback must pin a style system message
    first and constrain temperature."""
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
    first = captured["messages"][0]
    assert first["role"] == "system"
    assert "emoji" in first["content"].lower()
    assert captured["temperature"] <= 0.5
    assert captured["repeat_penalty"] >= 1.0
