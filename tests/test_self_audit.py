"""Tests for backend.services.self_audit — offline (injected fixtures only).

All tests pass run_records / specs / decisions explicitly so no vault or
disk access is needed.  The "all-None args" test patches the loaders to
return [] for the same reason.
"""
from __future__ import annotations

import sys
import types as stdlib_types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from backend.services.self_audit import audit


# ── Fixture helpers ───────────────────────────────────────────────────────────

def _spec(name: str, schedule: str | None = None) -> stdlib_types.SimpleNamespace:
    """Minimal spec stub (mirrors AgentSpec attributes used by audit())."""
    return stdlib_types.SimpleNamespace(name=name, schedule=schedule, enabled=True, description="")


def _run(
    run_id: str,
    agent: str,
    status: str = "success",
    iterations: int = 2,
    tool_calls: list | None = None,
    escalations: list | None = None,
    error: str | None = None,
) -> dict:
    return {
        "id": run_id,
        "agent": agent,
        "status": status,
        "iterations": iterations,
        "tool_calls": tool_calls or [],
        "escalations": escalations or [],
        "error": error,
        "started_at": "2026-06-27T10:00:00",
    }


def _esc(tool: str) -> dict:
    return {"tool": tool, "args": {}, "decision": "gate", "reason": "needs approval"}


def _decision(item_id: str, decision: str) -> dict:
    return {"item_id": item_id, "decision": decision, "ts": "2026-06-27T10:00:00Z"}


# ── Main fixture ──────────────────────────────────────────────────────────────

REPEATED_ERR = "max iterations (8) reached without a final answer"


@pytest.fixture
def fixture_data():
    """2 agents, mixed run outcomes, escalations on send_email, repeated error."""
    specs = [
        _spec("agent_a", schedule="0 7 * * *"),  # scheduled, 0 successes → idle_scheduled
        _spec("agent_b", schedule=None),           # no schedule, 3 runs    → manual_repeat
    ]
    runs = [
        # agent_a: 2 failed runs, each escalates send_email
        _run("r1", "agent_a", status="failed", iterations=8, error=REPEATED_ERR,
             escalations=[_esc("send_email")]),
        _run("r2", "agent_a", status="failed", iterations=8, error=REPEATED_ERR,
             escalations=[_esc("send_email")]),
        # agent_b: 3 manual runs (2 success, 1 failed)
        _run("r3", "agent_b", status="success", iterations=3,
             escalations=[_esc("send_email")]),
        _run("r4", "agent_b", status="success", iterations=3),
        _run("r5", "agent_b", status="failed", iterations=8, error=REPEATED_ERR),
    ]
    # Decisions: send_email approved in r1 + r2, dismissed in r3
    decisions = [
        _decision("r1:0", "approved"),
        _decision("r2:0", "approved"),
        _decision("r3:0", "dismissed"),
    ]
    return specs, runs, decisions


# ── Shape: top-level keys ─────────────────────────────────────────────────────

def test_audit_returns_all_top_level_keys(fixture_data):
    specs, runs, decisions = fixture_data
    result = audit(run_records=runs, specs=specs, decisions=decisions)
    assert set(result.keys()) == {"window", "agents", "tools", "scheduling", "autonomy", "friction"}


def test_window_counts(fixture_data):
    specs, runs, decisions = fixture_data
    result = audit(run_records=runs, specs=specs, decisions=decisions)
    w = result["window"]
    assert w["runs"] == 5
    assert w["agents"] == 2
    assert w["decisions"] == 3


# ── Agent stats ───────────────────────────────────────────────────────────────

def test_agents_sorted_by_runs_desc(fixture_data):
    specs, runs, decisions = fixture_data
    result = audit(run_records=runs, specs=specs, decisions=decisions)
    agents = result["agents"]
    assert len(agents) == 2
    # agent_b has 3 runs; agent_a has 2 — agent_b must come first
    assert agents[0]["name"] == "agent_b"
    assert agents[0]["runs"] == 3


def test_success_rate_computed(fixture_data):
    specs, runs, decisions = fixture_data
    result = audit(run_records=runs, specs=specs, decisions=decisions)
    by_name = {a["name"]: a for a in result["agents"]}
    # agent_a: 0 successes / 2 runs → 0.0
    assert by_name["agent_a"]["success_rate"] == 0.0
    # agent_b: 2 successes / 3 runs → 0.6667
    assert abs(by_name["agent_b"]["success_rate"] - round(2 / 3, 4)) < 1e-6


def test_scheduled_flag_reflects_spec(fixture_data):
    specs, runs, decisions = fixture_data
    result = audit(run_records=runs, specs=specs, decisions=decisions)
    by_name = {a["name"]: a for a in result["agents"]}
    assert by_name["agent_a"]["scheduled"] is True
    assert by_name["agent_b"]["scheduled"] is False


# ── Tool stats ────────────────────────────────────────────────────────────────

def test_most_gated_includes_send_email(fixture_data):
    specs, runs, decisions = fixture_data
    result = audit(run_records=runs, specs=specs, decisions=decisions)
    gated_tools = [g["tool"] for g in result["tools"]["most_gated"]]
    assert "send_email" in gated_tools


def test_most_gated_count_accurate(fixture_data):
    specs, runs, decisions = fixture_data
    result = audit(run_records=runs, specs=specs, decisions=decisions)
    gated = {g["tool"]: g["count"] for g in result["tools"]["most_gated"]}
    # send_email appears in escalations of r1, r2, r3 → count = 3
    assert gated.get("send_email") == 3


# ── Scheduling ────────────────────────────────────────────────────────────────

def test_idle_scheduled_contains_agent_a(fixture_data):
    specs, runs, decisions = fixture_data
    result = audit(run_records=runs, specs=specs, decisions=decisions)
    assert "agent_a" in result["scheduling"]["idle_scheduled"]


def test_manual_repeat_contains_agent_b(fixture_data):
    specs, runs, decisions = fixture_data
    result = audit(run_records=runs, specs=specs, decisions=decisions)
    assert "agent_b" in result["scheduling"]["manual_repeat"]


# ── Autonomy ──────────────────────────────────────────────────────────────────

def test_always_approved_when_only_approved():
    """Tool approved >=2 times and never dismissed → always_approved."""
    specs = [_spec("agent_c")]
    runs = [
        _run("e1", "agent_c", status="failed", escalations=[_esc("send_email")]),
        _run("e2", "agent_c", status="failed", escalations=[_esc("send_email")]),
    ]
    decisions = [_decision("e1:0", "approved"), _decision("e2:0", "approved")]
    result = audit(run_records=runs, specs=specs, decisions=decisions)
    assert "send_email" in result["autonomy"]["always_approved"]


def test_always_approved_not_when_also_dismissed(fixture_data):
    """send_email: 2 approvals + 1 dismissal → NOT in always_approved."""
    specs, runs, decisions = fixture_data
    result = audit(run_records=runs, specs=specs, decisions=decisions)
    assert "send_email" not in result["autonomy"]["always_approved"]


def test_always_dismissed_populated():
    """Tool dismissed >=2 times and never approved → always_dismissed."""
    specs = [_spec("agent_x")]
    runs = [
        _run("d1", "agent_x", status="success", escalations=[_esc("wire_transfer")]),
        _run("d2", "agent_x", status="success", escalations=[_esc("wire_transfer")]),
    ]
    decisions = [_decision("d1:0", "dismissed"), _decision("d2:0", "dismissed")]
    result = audit(run_records=runs, specs=specs, decisions=decisions)
    assert "wire_transfer" in result["autonomy"]["always_dismissed"]
    assert "wire_transfer" not in result["autonomy"]["always_approved"]


# ── Friction ──────────────────────────────────────────────────────────────────

def test_friction_lists_repeated_error(fixture_data):
    specs, runs, decisions = fixture_data
    result = audit(run_records=runs, specs=specs, decisions=decisions)
    # REPEATED_ERR appears 3 times across r1, r2, r5
    assert len(result["friction"]) >= 1


def test_friction_excludes_one_off_errors():
    """An error that appears only once must not appear in friction."""
    specs = [_spec("agent_z")]
    runs = [
        _run("z1", "agent_z", status="failed", error="unique error abc"),
        _run("z2", "agent_z", status="failed", error="another unique xyz"),
    ]
    result = audit(run_records=runs, specs=specs, decisions=[])
    assert result["friction"] == []


# ── Deduplication ─────────────────────────────────────────────────────────────

def test_dedupe_keeps_final_record_over_running():
    """RUNNING + final record for same id → only the final one is counted."""
    running = _run("dup1", "ag", status="running", iterations=0)
    final = _run("dup1", "ag", status="success", iterations=4)
    result = audit(run_records=[running, final], specs=[], decisions=[])
    assert result["window"]["runs"] == 1
    by_name = {a["name"]: a for a in result["agents"]}
    assert by_name["ag"]["last_status"] == "success"
    assert by_name["ag"]["successes"] == 1


# ── Robustness: malformed records ────────────────────────────────────────────

def test_malformed_records_do_not_crash():
    """Records missing expected fields must not raise."""
    bad_runs = [
        {},
        {"id": "x"},
        {"agent": None, "status": "???"},
        {"id": "ok", "agent": "a", "status": "success", "iterations": 1,
         "tool_calls": "not-a-list", "escalations": None},
    ]
    result = audit(run_records=bad_runs, specs=[], decisions=[])
    assert isinstance(result, dict)
    assert "window" in result


# ── all-None args (offline, loaders patched to []) ───────────────────────────

def test_audit_with_all_none_args_does_not_crash():
    """audit() with all-None args must return a valid dict even offline."""
    mock_store = MagicMock()
    mock_store.return_value.list.return_value = []
    mock_loader = MagicMock()
    mock_loader.return_value.list_all.return_value = []

    with patch("backend.services.agent_runner.RunStore", mock_store), \
         patch("backend.services.agent_loader.AgentLoader", mock_loader), \
         patch("backend.services.approvals.list_decisions", return_value=[]), \
         patch("backend.vault.agentic_os_dir", return_value=Path("/tmp/fake-agentic-os")):
        result = audit()

    assert isinstance(result, dict)
    for key in ("window", "agents", "tools", "scheduling", "autonomy", "friction"):
        assert key in result
    assert result["window"]["runs"] == 0
    assert result["window"]["agents"] == 0
    assert result["window"]["decisions"] == 0
