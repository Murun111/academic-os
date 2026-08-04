"""Tests for trajectory memory (roadmap B3).

Hermetic: the Ollama embed() is monkeypatched to deterministic vectors and the
store points at a tmp DB. Covers: store gating (enabled + success + critic-pass
only), retrieval ranking by similarity, few-shot formatting, the flag gate, and
fail-open behavior.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

import pytest

from backend.services import trajectory_memory as tm
from backend.services.trajectory_memory import (
    TrajectoryStore,
    format_fewshot,
    maybe_inject,
    retrieve,
    store_trajectory,
)


class _Status(str, Enum):
    SUCCESS = "success"
    FAILED = "failed"


@dataclass
class _Run:
    id: str = "r1"
    agent: str = "daily-brief"
    status: _Status = _Status.SUCCESS
    result: Optional[str] = "done"
    finished_at: str = "2026-06-30T10:00:00"
    tool_calls: list = field(default_factory=list)
    critic: Optional[dict] = field(default_factory=lambda: {"verdict": "pass"})


@dataclass
class _Spec:
    name: str = "daily-brief"
    description: str = "Summarize the day"


def _run(coro):
    return asyncio.run(coro)


# A fake embedder: map known phrases to 2-D unit-ish vectors so cosine ordering
# is deterministic and offline.
_VECS = {
    "weather": [1.0, 0.0],
    "finance": [0.0, 1.0],
    "weather forecast": [0.9, 0.1],
}


def _fake_embed_factory():
    async def _fake_embed(text: str):
        for key, vec in _VECS.items():
            if key in text:
                return vec
        return [0.5, 0.5]
    return _fake_embed


@pytest.fixture
def enabled(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_TRAJECTORY_MEMORY", "1")
    monkeypatch.setattr(tm, "embed", _fake_embed_factory())
    monkeypatch.setattr(tm, "_default_store",
                        TrajectoryStore(db_path=tmp_path / "traj.db"))


# --- gating -----------------------------------------------------------------

def test_store_skipped_when_disabled(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_TRAJECTORY_MEMORY", "0")
    assert _run(store_trajectory(_Run(), _Spec())) is False


def test_store_skips_failed_run(enabled):
    run = _Run(status=_Status.FAILED, critic={"verdict": "pass"})
    assert _run(store_trajectory(run, _Spec())) is False


def test_store_skips_critic_not_passed(enabled):
    assert _run(store_trajectory(_Run(critic={"verdict": "retry"}), _Spec())) is False
    assert _run(store_trajectory(_Run(critic=None), _Spec())) is False


def test_store_skips_disabled_critic_pass(enabled):
    # AGENT_CRITIC=0 yields verdict "pass" reason "critic disabled" — NOT a real
    # verification, so it must not graduate unreviewed runs into the corpus.
    run = _Run(critic={"verdict": "pass", "reason": "critic disabled"})
    assert _run(store_trajectory(run, _Spec())) is False


def test_store_succeeds_for_passed_run(enabled):
    assert _run(store_trajectory(_Run(), _Spec())) is True


# --- retrieval ranking ------------------------------------------------------

def test_retrieve_ranks_by_similarity(enabled):
    _run(store_trajectory(
        _Run(id="w", tool_calls=[{"tool": "get_weather"}]),
        _Spec(description="weather report"),
    ))
    _run(store_trajectory(
        _Run(id="f", tool_calls=[{"tool": "get_quote"}]),
        _Spec(description="finance report"),
    ))
    top = _run(retrieve("weather forecast", k=1))
    assert len(top) == 1 and top[0]["run_id"] == "w"


def test_retrieve_scopes_to_agent(enabled):
    _run(store_trajectory(
        _Run(id="wa", agent="weatherbot", tool_calls=[{"tool": "t"}]),
        _Spec(name="weatherbot", description="weather report"),
    ))
    _run(store_trajectory(
        _Run(id="fa", agent="financebot", tool_calls=[{"tool": "t"}]),
        _Spec(name="financebot", description="weather-ish finance note"),
    ))
    # Even though both mention weather, an agent retrieves only its own.
    got = _run(retrieve("weather", k=5, agent="weatherbot"))
    assert {r["run_id"] for r in got} == {"wa"}


def test_retrieve_empty_goal_returns_nothing(enabled):
    assert _run(retrieve("  ", k=3)) == []


def test_retrieve_disabled_returns_nothing(monkeypatch):
    monkeypatch.setenv("AGENT_TRAJECTORY_MEMORY", "0")
    assert _run(retrieve("weather", k=3)) == []


def test_approach_captures_tool_sequence(enabled):
    _run(store_trajectory(
        _Run(id="seq", tool_calls=[{"tool": "a"}, {"tool": "b"}]),
        _Spec(description="weather thing"),
    ))
    got = _run(retrieve("weather", k=1))
    assert got[0]["approach"] == "a → b"


def test_approach_direct_answer_when_no_tools(enabled):
    _run(store_trajectory(_Run(id="d", tool_calls=[]), _Spec(description="weather x")))
    assert _run(retrieve("weather", k=1))[0]["approach"] == "(direct answer, no tools)"


# --- formatting + maybe_inject ----------------------------------------------

def test_format_fewshot_empty_is_blank():
    assert format_fewshot([]) == ""


def test_format_fewshot_renders_entries():
    out = format_fewshot([{"goal": "G", "approach": "a → b", "outcome": "done"}])
    assert "Goal: G" in out and "a → b" in out and "guidance" in out.lower()


def test_maybe_inject_offwhen_disabled(monkeypatch):
    monkeypatch.setenv("AGENT_TRAJECTORY_MEMORY", "0")
    assert _run(maybe_inject("weather")) == ""


def test_maybe_inject_returns_block_when_enabled(enabled):
    _run(store_trajectory(_Run(id="w", tool_calls=[{"tool": "t"}]),
                          _Spec(description="weather report")))
    block = _run(maybe_inject("weather forecast"))
    assert "weather report" in block


# --- fail-open --------------------------------------------------------------

def test_store_fail_open_on_embed_error(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("AGENT_TRAJECTORY_MEMORY", "1")
    monkeypatch.setattr(tm, "_default_store", TrajectoryStore(db_path=tmp_path / "t.db"))

    async def _boom(text):
        raise ConnectionError("ollama down")
    monkeypatch.setattr(tm, "embed", _boom)
    assert _run(store_trajectory(_Run(), _Spec())) is False  # swallowed, not raised
    assert "store failed" in capsys.readouterr().out


def test_retrieve_fail_open_on_embed_error(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_TRAJECTORY_MEMORY", "1")
    monkeypatch.setattr(tm, "_default_store", TrajectoryStore(db_path=tmp_path / "t.db"))

    async def _boom(text):
        raise ConnectionError("down")
    monkeypatch.setattr(tm, "embed", _boom)
    assert _run(retrieve("weather", k=3)) == []
