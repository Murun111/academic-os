"""Tests for backend.services.consensus — multi-model second opinion.

Fully OFFLINE: llm_hub.status_all and get_backend are monkeypatched so no real
CLI is ever launched. We assert panel resolution (online-only), concurrent
stance collection, graceful drop of failing backends, and synthesis wiring.
"""
from __future__ import annotations

import pytest

from backend.llm_hub import ChatResult, ProbeResult
from backend.services import consensus as C


def _status(online: set[str]):
    async def _fake():
        names = ["ollama", "codex", "claude", "droid", "cursor", "gemini", "hermes"]
        return {n: ProbeResult(online=(n in online)) for n in names}
    return _fake


class _FakeBackend:
    def __init__(self, name, reply="Yes, because it scales.", fail=False):
        self.name = name
        self._reply = reply
        self._fail = fail

    async def chat(self, messages, model=""):
        if self._fail:
            raise RuntimeError("boom")
        return ChatResult(backend=self.name, model=f"{self.name}-m", content=self._reply)


def _get_backend_factory(backends: dict):
    def _get(name):
        if name not in backends:
            raise KeyError(name)
        return backends[name]
    return _get


@pytest.mark.asyncio
async def test_consensus_synthesizes_online_panel(monkeypatch):
    monkeypatch.setattr(C, "status_all", _status({"claude", "codex", "droid", "ollama"}))
    backends = {
        "claude": _FakeBackend("claude", "Yes — strongest option."),
        "codex": _FakeBackend("codex", "No — too risky."),
        "droid": _FakeBackend("droid", "It depends on scale."),
        "ollama": _FakeBackend("ollama", "SYNTHESIS: mixed, lean yes."),
    }
    monkeypatch.setattr(C, "get_backend", _get_backend_factory(backends))

    res = await C.consensus("Should we migrate to GraphQL?")

    assert res["error"] == ""
    assert set(res["panel"]) == {"claude", "codex", "droid"}      # online preferred panel
    assert {s["backend"] for s in res["stances"]} == {"claude", "codex", "droid"}
    assert res["synthesis"] == "SYNTHESIS: mixed, lean yes."       # came from ollama synthesizer


@pytest.mark.asyncio
async def test_consensus_drops_offline_panel_members(monkeypatch):
    # Only claude + ollama online → panel shrinks to claude.
    monkeypatch.setattr(C, "status_all", _status({"claude", "ollama"}))
    backends = {
        "claude": _FakeBackend("claude", "Yes."),
        "ollama": _FakeBackend("ollama", "Final: yes."),
    }
    monkeypatch.setattr(C, "get_backend", _get_backend_factory(backends))

    res = await C.consensus("Ship it?")

    assert res["panel"] == ["claude"]
    assert res["answered"] == ["claude"]


@pytest.mark.asyncio
async def test_consensus_skips_failing_backend(monkeypatch):
    monkeypatch.setattr(C, "status_all", _status({"claude", "codex", "droid", "ollama"}))
    backends = {
        "claude": _FakeBackend("claude", "Yes."),
        "codex": _FakeBackend("codex", fail=True),       # errors → dropped
        "droid": _FakeBackend("droid", "No."),
        "ollama": _FakeBackend("ollama", "Synthesis."),
    }
    monkeypatch.setattr(C, "get_backend", _get_backend_factory(backends))

    res = await C.consensus("Decision?")

    assert "codex" not in res["answered"]
    assert set(res["answered"]) == {"claude", "droid"}


@pytest.mark.asyncio
async def test_consensus_empty_question():
    res = await C.consensus("   ")
    assert res["error"] == "question is required"
    assert res["stances"] == []


@pytest.mark.asyncio
async def test_consensus_no_backends_online(monkeypatch):
    monkeypatch.setattr(C, "status_all", _status(set()))
    res = await C.consensus("Anything?")
    assert res["error"] == "no_backends"
    assert res["stances"] == []
