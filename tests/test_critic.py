"""Tests for backend.services.critic — verify-before-commit.

Hermetic: the Ollama backend is mocked via get_backend; memory recall is stubbed.
Every test opts the critic ON (the suite disables it by default — see conftest).
"""
from __future__ import annotations

import pytest

from backend.llm_hub import ChatResult
from backend.services import critic as C


@pytest.fixture(autouse=True)
def enable_and_stub(monkeypatch):
    monkeypatch.setenv("AGENT_CRITIC", "1")
    monkeypatch.setattr(C, "_recall_facts", lambda goal: "")  # no DB/embeddings


class _Backend:
    def __init__(self, content):
        self._content = content

    async def chat(self, messages, model=""):
        return ChatResult(backend="ollama", model="m", content=self._content)


def _mock_backend(monkeypatch, content):
    monkeypatch.setattr(C, "get_backend", lambda name: _Backend(content))


@pytest.mark.asyncio
async def test_pass_verdict(monkeypatch):
    _mock_backend(monkeypatch, '{"verdict": "pass", "reason": "good", "contradicts_memory": false}')
    v = await C.verify("write a brief", "Here is the brief …")
    assert v.verdict == "pass"
    assert v.contradicts_memory is False


@pytest.mark.asyncio
async def test_retry_verdict(monkeypatch):
    _mock_backend(monkeypatch, '{"verdict":"retry","reason":"incomplete"}')
    v = await C.verify("list 3 items", "only one item")
    assert v.verdict == "retry"
    assert "incomplete" in v.reason


@pytest.mark.asyncio
async def test_escalate_with_contradiction(monkeypatch):
    _mock_backend(monkeypatch, 'sure: {"verdict":"escalate","reason":"contradicts net worth","contradicts_memory":true}')
    v = await C.verify("report finances", "net worth is +$1M")
    assert v.verdict == "escalate"
    assert v.contradicts_memory is True


@pytest.mark.asyncio
async def test_empty_output_is_retry_without_calling_model(monkeypatch):
    # If the model were called it would raise — proves the short-circuit.
    def _boom(name):
        raise AssertionError("model should not be called for empty output")
    monkeypatch.setattr(C, "get_backend", _boom)
    v = await C.verify("anything", "   ")
    assert v.verdict == "retry"


@pytest.mark.asyncio
async def test_fail_open_on_backend_error(monkeypatch):
    class _Boom:
        async def chat(self, *a, **k):
            raise RuntimeError("ollama down")
    monkeypatch.setattr(C, "get_backend", lambda name: _Boom())
    v = await C.verify("goal", "output")
    assert v.verdict == "pass"           # fail-open
    assert "fail-open" in v.reason


@pytest.mark.asyncio
async def test_unparseable_response_defaults_pass(monkeypatch):
    _mock_backend(monkeypatch, "I think it's fine, no JSON here")
    v = await C.verify("goal", "output")
    assert v.verdict == "pass"


@pytest.mark.asyncio
async def test_disabled_via_env_short_circuits(monkeypatch):
    monkeypatch.setenv("AGENT_CRITIC", "0")
    def _boom(name):
        raise AssertionError("disabled critic must not call the model")
    monkeypatch.setattr(C, "get_backend", _boom)
    v = await C.verify("goal", "output")
    assert v.verdict == "pass"
    assert "disabled" in v.reason
