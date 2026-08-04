"""Tests for the unified trajectory trace (roadmap B1).

Covers: happy path (record→recent→get), corrupt-line tolerance, fail-open on a
broken store, AGENT_TRACE toggle, and the pure folding function.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

import pytest

from backend.services import trace
from backend.services.trace import TraceStore, record_trace, trajectory_from_run


# --- Minimal stand-ins mirroring AgentRun / AgentSpec shape ----------------

class _Status(str, Enum):
    SUCCESS = "success"
    FAILED = "failed"


@dataclass
class _FakeRun:
    id: str = "abc123"
    agent: str = "daily-brief"
    status: _Status = _Status.SUCCESS
    started_at: str = "2026-06-30T10:00:00"
    finished_at: str = "2026-06-30T10:00:02"
    result: Optional[str] = "all good\nmulti-line"
    error: Optional[str] = None
    duration_seconds: float = 2.5
    trigger: Optional[str] = "manual"
    tool_calls: list = field(default_factory=list)
    critic: Optional[dict] = None


@dataclass
class _FakeSpec:
    name: str = "daily-brief"
    description: str = "Summarize the day"


@pytest.fixture
def store(tmp_path):
    return TraceStore(base_dir=tmp_path / "traces")


# --- trajectory_from_run (pure) --------------------------------------------

def test_fold_shape_and_goal_from_description():
    run = _FakeRun(
        tool_calls=[{"tool": "search", "args": {"q": "x"}, "result": "found\nstuff"}],
        critic={"verdict": "pass", "reason": "ok"},
    )
    rec = trajectory_from_run(run, _FakeSpec())
    assert rec["run_id"] == "abc123"
    assert rec["agent"] == "daily-brief"
    assert rec["goal"] == "Summarize the day"
    assert rec["outcome"] == "success"
    assert rec["timing_ms"] == 2500
    assert rec["critic"] == {"verdict": "pass", "reason": "ok"}
    # tool call folded: name + stable args hash + single-line summary
    tc = rec["tool_calls"][0]
    assert tc["name"] == "search"
    assert len(tc["args_hash"]) == 12
    assert "\n" not in tc["result_summary"]
    # result summary is single-line and bounded
    assert "\n" not in rec["result_summary"]


def test_fold_goal_falls_back_to_name_then_empty():
    assert trajectory_from_run(_FakeRun(), _FakeSpec(description=""))["goal"] == "daily-brief"
    assert trajectory_from_run(_FakeRun(), None)["goal"] == ""


def test_fold_failed_run_uses_error_summary():
    run = _FakeRun(status=_Status.FAILED, result=None, error="boom")
    rec = trajectory_from_run(run, _FakeSpec())
    assert rec["outcome"] == "failed"
    assert rec["result_summary"] == "boom"


def test_fold_reads_production_result_preview_key():
    # The runner records tool output under "result_preview" (agent_runner.py:494/524),
    # NOT "result". The fold must read the real key or summaries are always empty.
    run = _FakeRun(
        tool_calls=[{"tool": "money.balance", "args": {}, "result_preview": "$42.00"}],
    )
    rec = trajectory_from_run(run, _FakeSpec())
    assert rec["tool_calls"][0]["result_summary"] == "$42.00"


def test_fold_gated_call_records_gate_preview():
    run = _FakeRun(
        tool_calls=[{"tool": "send_email", "args": {"to": "x"}, "gate": "gate",
                     "result_preview": "[gate] needs approval"}],
    )
    rec = trajectory_from_run(run, _FakeSpec())
    assert rec["tool_calls"][0]["result_summary"] == "[gate] needs approval"


@pytest.mark.parametrize("status", ["timeout", "cancelled", "interrupted"])
def test_fold_handles_all_terminal_states(status):
    class _S(str, Enum):
        X = status
    rec = trajectory_from_run(_FakeRun(status=_S.X), _FakeSpec())
    assert rec["outcome"] == status


def test_fold_handles_none_duration_and_finished_at():
    # An interrupted/crashed run may never set duration_seconds or finished_at.
    run = _FakeRun(duration_seconds=None, finished_at=None)
    rec = trajectory_from_run(run, _FakeSpec())  # must not raise
    assert rec["timing_ms"] == 0
    assert rec["ts"]  # falls back to now() when finished_at is missing


def test_fold_timing_rounds_not_truncates():
    assert trajectory_from_run(_FakeRun(duration_seconds=2.9999), _FakeSpec())["timing_ms"] == 3000


def test_fold_ts_partitions_by_finished_at():
    run = _FakeRun(finished_at="2026-06-29T23:59:59.900000")
    assert trajectory_from_run(run, _FakeSpec())["ts"][:10] == "2026-06-29"


# --- TraceStore round-trip --------------------------------------------------

def test_append_recent_get_roundtrip(store):
    store.append({"run_id": "r1", "ts": "2026-06-30T10:00:00", "outcome": "success"})
    store.append({"run_id": "r2", "ts": "2026-06-30T10:01:00", "outcome": "failed"})
    recent = store.recent()
    assert [r["run_id"] for r in recent] == ["r1", "r2"]
    assert store.get("r2")["outcome"] == "failed"
    assert store.get("missing") is None


def test_recent_n_limit_and_order(store):
    for i in range(5):
        store.append({"run_id": f"r{i}", "ts": "2026-06-30T10:00:00"})
    assert [r["run_id"] for r in store.recent(n=2)] == ["r3", "r4"]


def test_get_returns_last_match(store):
    store.append({"run_id": "dup", "ts": "2026-06-30T10:00:00", "outcome": "running"})
    store.append({"run_id": "dup", "ts": "2026-06-30T10:00:01", "outcome": "success"})
    assert store.get("dup")["outcome"] == "success"


def test_recent_skips_corrupt_lines(store):
    path = store.base_dir / "2026-06-30.jsonl"
    path.write_text(
        json.dumps({"run_id": "good1", "ts": "2026-06-30T10:00:00"}) + "\n"
        + "{ this is not json\n"
        + "\n"  # blank line
        + json.dumps({"run_id": "good2", "ts": "2026-06-30T10:00:01"}) + "\n"
    )
    recent = store.recent()
    # corrupt + blank skipped; both valid records returned with correct count
    assert [r["run_id"] for r in recent] == ["good1", "good2"]


def test_date_partitioning(store):
    store.append({"run_id": "a", "ts": "2026-06-29T23:59:00"})
    store.append({"run_id": "b", "ts": "2026-06-30T00:01:00"})
    files = sorted(p.name for p in store.base_dir.glob("*.jsonl"))
    assert files == ["2026-06-29.jsonl", "2026-06-30.jsonl"]


# --- record_trace (toggle + fail-open) -------------------------------------

def test_record_trace_disabled_returns_none(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_TRACE", "0")
    assert record_trace(_FakeRun(), _FakeSpec()) is None


def test_record_trace_writes_when_enabled(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_TRACE", "1")
    monkeypatch.setattr(trace, "_default_store", TraceStore(base_dir=tmp_path / "t"))
    rec = record_trace(_FakeRun(), _FakeSpec())
    assert rec is not None and rec["run_id"] == "abc123"
    assert trace._store().get("abc123")["goal"] == "Summarize the day"


def test_record_trace_fail_open_on_broken_store(monkeypatch, capsys):
    monkeypatch.setenv("AGENT_TRACE", "1")

    class _BrokenStore:
        def append(self, record):
            raise IOError("disk full")

    monkeypatch.setattr(trace, "_store", lambda: _BrokenStore())
    # A store write error must NOT propagate into the run lifecycle.
    assert record_trace(_FakeRun(), _FakeSpec()) is None
    assert "record failed" in capsys.readouterr().out
