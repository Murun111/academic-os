"""Tests for backend.services.approvals — Phase 4.

All tests run OFFLINE:
- DECISIONS_PATH is monkeypatched to a tmp file (no vault touched).
- A FakeRunStore drives list_pending() without a real JSONL on disk.

Coverage:
- list_pending expands escalations with correct id format (<run_id>:<idx>).
- list_pending excludes items already in the decisions store.
- list_pending dedupes duplicate run records (RUNNING + final), preferring
  the record with escalations.
- decide() appends a valid record and validates the decision value.
- decide() raises ValueError on an invalid decision string.
- list_decisions() roundtrips the JSONL correctly; returns [] when missing.
"""
from __future__ import annotations

import types
from pathlib import Path

import pytest

import backend.services.approvals as approvals_mod
from backend.services.approvals import list_pending, decide, list_decisions, execute_item


# ── Fake helpers ──────────────────────────────────────────────────────────────

class FakeRunStore:
    """In-memory stand-in for RunStore."""

    def __init__(self, runs: list[dict]):
        self._runs = runs

    def list(self, agent=None, limit: int = 50) -> list[dict]:
        out = self._runs if agent is None else [r for r in self._runs if r.get("agent") == agent]
        return out[-limit:]


def _run(
    run_id: str,
    agent: str = "coo",
    started_at: str = "2026-06-26T07:00:00",
    escalations: list[dict] | None = None,
) -> dict:
    return {
        "id": run_id,
        "agent": agent,
        "status": "success",
        "started_at": started_at,
        "escalations": escalations or [],
    }


def _esc(tool: str = "send_email", args: dict | None = None, reason: str = "needs approval") -> dict:
    return {"tool": tool, "args": args or {"to": "cfo@example.com"}, "decision": "escalate", "reason": reason}


# ── Fixture: redirect DECISIONS_PATH to tmp ───────────────────────────────────

@pytest.fixture(autouse=True)
def patch_decisions_path(monkeypatch, tmp_path: Path):
    tmp_file = tmp_path / "approvals.jsonl"
    monkeypatch.setattr(approvals_mod, "DECISIONS_PATH", tmp_file)
    monkeypatch.setattr(approvals_mod, "EXECUTIONS_PATH", tmp_path / "approvals_executed.jsonl")
    return tmp_file


# ── Durability: execution idempotency ─────────────────────────────────────────

def test_execution_ledger_roundtrip_and_idempotency():
    assert approvals_mod.was_executed("r1:0") is False
    approvals_mod.mark_executed("r1:0", "email sent")
    assert approvals_mod.was_executed("r1:0") is True   # recorded
    assert approvals_mod.was_executed("r1:1") is False  # a different action is unaffected


# ── list_pending: basic expansion ─────────────────────────────────────────────

def test_list_pending_expands_escalations_to_items():
    store = FakeRunStore([
        _run("run1", escalations=[_esc("send_email"), _esc("write_file")]),
    ])
    items = list_pending(store)
    assert len(items) == 2
    assert items[0]["id"] == "run1:0" or items[1]["id"] == "run1:0"
    ids = {i["id"] for i in items}
    assert "run1:0" in ids
    assert "run1:1" in ids


def test_list_pending_item_has_correct_fields():
    store = FakeRunStore([
        _run("run42", agent="cfo", started_at="2026-06-26T08:00:00",
             escalations=[_esc("wire_transfer", {"amount": 1000}, "large amount")]),
    ])
    items = list_pending(store)
    assert len(items) == 1
    item = items[0]
    assert item["id"] == "run42:0"
    assert item["run_id"] == "run42"
    assert item["idx"] == 0
    assert item["agent"] == "cfo"
    assert item["tool"] == "wire_transfer"
    assert item["args"] == {"amount": 1000}
    assert item["reason"] == "large amount"
    assert item["ts"] == "2026-06-26T08:00:00"
    assert item["status"] == "pending"


def test_list_pending_empty_when_no_escalations():
    store = FakeRunStore([
        _run("run1", escalations=[]),
        _run("run2"),
    ])
    assert list_pending(store) == []


# ── list_pending: excludes decided items ──────────────────────────────────────

def test_list_pending_excludes_decided_items():
    store = FakeRunStore([
        _run("run1", escalations=[_esc("send_email"), _esc("write_file")]),
    ])
    # Decide the first escalation
    decide("run1:0", "approved")

    items = list_pending(store)
    ids = [i["id"] for i in items]
    assert "run1:0" not in ids
    assert "run1:1" in ids


def test_list_pending_excludes_dismissed_items():
    store = FakeRunStore([
        _run("runX", escalations=[_esc("delete_record")]),
    ])
    decide("runX:0", "dismissed")
    assert list_pending(store) == []


# ── list_pending: deduplication ───────────────────────────────────────────────

def test_list_pending_dedupes_duplicate_run_records():
    """runs.jsonl writes a RUNNING record (no escalations) then a final record
    (with escalations). list_pending must collapse these and produce items only once."""
    running_record = _run("runDup", escalations=[])          # RUNNING record: no escalations yet
    final_record = _run("runDup", escalations=[_esc("send_email")])  # final record: has escalation

    store = FakeRunStore([running_record, final_record])
    items = list_pending(store)
    # Should produce exactly one item, not two (not zero, not duplicated)
    assert len(items) == 1
    assert items[0]["id"] == "runDup:0"


def test_list_pending_dedupes_keeps_record_with_escalations():
    """Even when final record appears before RUNNING record in the list, the one
    with escalations should win."""
    final_record = _run("runDup2", escalations=[_esc("send_email")])
    running_record = _run("runDup2", escalations=[])

    store = FakeRunStore([final_record, running_record])
    items = list_pending(store)
    assert len(items) == 1
    assert items[0]["run_id"] == "runDup2"


# ── decide(): validation and persistence ─────────────────────────────────────

def test_decide_appends_record(tmp_path: Path, patch_decisions_path: Path):
    rec = decide("run1:0", "approved")
    assert rec["item_id"] == "run1:0"
    assert rec["decision"] == "approved"
    assert "ts" in rec
    assert patch_decisions_path.exists()


def test_decide_dismissed_appends_record(patch_decisions_path: Path):
    rec = decide("run2:1", "dismissed")
    assert rec["decision"] == "dismissed"


def test_decide_raises_on_invalid_decision():
    with pytest.raises(ValueError, match="Invalid decision"):
        decide("run1:0", "ignored")


def test_decide_raises_on_empty_decision():
    with pytest.raises(ValueError):
        decide("run1:0", "")


def test_decide_creates_parent_dir(tmp_path: Path, monkeypatch):
    nested = tmp_path / "deep" / "nested" / "approvals.jsonl"
    monkeypatch.setattr(approvals_mod, "DECISIONS_PATH", nested)
    decide("run1:0", "approved")
    assert nested.exists()


# ── list_decisions(): roundtrip ───────────────────────────────────────────────

def test_list_decisions_empty_when_file_missing():
    assert list_decisions() == []


def test_list_decisions_roundtrips_records():
    decide("run1:0", "approved")
    decide("run2:0", "dismissed")
    decs = list_decisions()
    assert len(decs) == 2
    item_ids = {d["item_id"] for d in decs}
    assert "run1:0" in item_ids
    assert "run2:0" in item_ids


def test_list_decisions_returns_correct_decision_values():
    decide("runA:0", "approved")
    decide("runB:0", "dismissed")
    decs = {d["item_id"]: d["decision"] for d in list_decisions()}
    assert decs["runA:0"] == "approved"
    assert decs["runB:0"] == "dismissed"


# ── integration: decide then pending is empty ─────────────────────────────────

def test_decide_removes_from_pending():
    store = FakeRunStore([
        _run("runZ", escalations=[_esc("send_report")]),
    ])
    assert len(list_pending(store)) == 1
    decide("runZ:0", "approved")
    assert list_pending(store) == []


# ── execute_item ──────────────────────────────────────────────────────────────

def _fake_tool(name: str, handler):
    """Build a minimal tool-like object with .name and .handler."""
    return types.SimpleNamespace(name=name, handler=handler)


@pytest.mark.asyncio
async def test_execute_item_runs_registered_tool():
    """A registered tool whose handler echoes kwargs should return executed=True."""
    async def echo(**kwargs):
        return {"echoed": kwargs}

    tools = [_fake_tool("echo_tool", echo)]
    item = {"tool": "echo_tool", "args": {"x": 1, "y": "hello"}}
    result = await execute_item(item, tools)
    assert result["executed"] is True
    assert result["result"] == {"echoed": {"x": 1, "y": "hello"}}


@pytest.mark.asyncio
async def test_execute_item_unknown_tool_returns_not_executable():
    """An unknown tool name should return executed=False with a clear reason."""
    tools = [_fake_tool("some_tool", None)]
    item = {"tool": "missing_tool", "args": {}}
    result = await execute_item(item, tools)
    assert result["executed"] is False
    assert "no such tool" in result["reason"]
    assert "missing_tool" in result["reason"]


@pytest.mark.asyncio
async def test_execute_item_handler_raises_does_not_propagate():
    """execute_item must never raise; handler exceptions become executed=False."""
    async def boom(**kwargs):
        raise RuntimeError("handler exploded")

    tools = [_fake_tool("boom_tool", boom)]
    item = {"tool": "boom_tool", "args": {"a": 1}}
    result = await execute_item(item, tools)
    assert result["executed"] is False
    assert "RuntimeError" in result["reason"]
