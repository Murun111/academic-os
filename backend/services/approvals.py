"""Approval inbox service — Phase 4.

Gated escalations produced by the agent runner are surfaced here for
human review. Each escalation embedded in a run record is expanded into
a discrete "pending item" the UI can approve or dismiss.

IMPORTANT SCOPE NOTE:
Approving an item does NOT auto-execute the underlying agent action.
Agents do not yet have outward-execution capability (Phase 4 scope).
Approval records the human's decision and removes the item from pending
so the inbox stays clean. Auto-execution is a future phase concern.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.vault import agentic_os_dir

DECISIONS_PATH: Path = agentic_os_dir() / "data" / "approvals.jsonl"
# Durability ledger: which approved actions have actually been EXECUTED, so a
# replay/retry of the decide endpoint can never fire the same side-effect twice.
EXECUTIONS_PATH: Path = agentic_os_dir() / "data" / "approvals_executed.jsonl"

_VALID_DECISIONS = {"approved", "dismissed"}


# ── helpers ───────────────────────────────────────────────────────────────────

def _decided_ids() -> set[str]:
    """Return the set of item_ids that already have a decision recorded."""
    return {d["item_id"] for d in list_decisions()}


def _iso_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ── public API ────────────────────────────────────────────────────────────────

def list_pending(run_store: Any, limit: int = 50) -> list[dict]:
    """Expand recent run escalations into approval-inbox items.

    Algorithm:
    1. Fetch the last `limit` run records from run_store.
    2. Dedupe by run id — runs.jsonl contains both RUNNING and final records
       for each run (append-only log). Prefer the record that has escalations
       (i.e. the final one). Collapse on id, keeping whichever has the longer
       escalations list.
    3. For each deduplicated run, enumerate its escalations. Each escalation
       at index `idx` becomes an item with id ``"<run_id>:<idx>"``.
    4. Exclude items whose id already appears in the decisions store.
    5. Return newest-first (by run started_at, descending).
    """
    raw: list[dict] = run_store.list(limit=limit)

    # Dedupe by run id — keep the record that has the most escalations.
    by_id: dict[str, dict] = {}
    for run in raw:
        rid = run.get("id", "")
        if not rid:
            continue
        existing = by_id.get(rid)
        if existing is None:
            by_id[rid] = run
        else:
            # Prefer whichever has more escalations (the final record).
            if len(run.get("escalations", [])) >= len(existing.get("escalations", [])):
                by_id[rid] = run

    decided = _decided_ids()
    items: list[dict] = []
    for run in by_id.values():
        for idx, esc in enumerate(run.get("escalations", [])):
            item_id = f"{run['id']}:{idx}"
            if item_id in decided:
                continue
            items.append({
                "id": item_id,
                "run_id": run["id"],
                "idx": idx,
                "agent": run.get("agent"),
                "tool": esc.get("tool"),
                "args": esc.get("args"),
                "reason": esc.get("reason"),
                "ts": run.get("started_at"),
                "status": "pending",
            })

    # Newest first — sort by ts descending (ISO strings sort lexicographically).
    items.sort(key=lambda x: x.get("ts") or "", reverse=True)
    return items


def decide(item_id: str, decision: str) -> dict:
    """Record a human decision for an approval item.

    Parameters
    ----------
    item_id:
        The compound id ``"<run_id>:<idx>"`` of the pending item.
    decision:
        Must be ``"approved"`` or ``"dismissed"``; raises ``ValueError`` otherwise.

    Returns
    -------
    dict
        The decision record that was appended to DECISIONS_PATH.

    Note
    ----
    Approving does NOT execute the underlying action. The agent runner does not
    yet have outward-execution capability (Phase 4 scope). This call records the
    human's decision and removes the item from the pending inbox only.
    """
    if decision not in _VALID_DECISIONS:
        raise ValueError(
            f"Invalid decision {decision!r}. Must be one of: {sorted(_VALID_DECISIONS)}"
        )
    record: dict = {
        "item_id": item_id,
        "decision": decision,
        "ts": _iso_utc(),
    }
    DECISIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with DECISIONS_PATH.open("a") as fh:
        fh.write(json.dumps(record) + "\n")
    return record


def list_decisions() -> list[dict]:
    """Return all recorded decisions (approved or dismissed).

    Returns an empty list if DECISIONS_PATH does not yet exist.
    """
    if not DECISIONS_PATH.exists():
        return []
    out: list[dict] = []
    with DECISIONS_PATH.open() as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def was_executed(item_id: str) -> bool:
    """True if this approval item's action has already been executed (idempotency)."""
    if not EXECUTIONS_PATH.exists():
        return False
    with EXECUTIONS_PATH.open() as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                if json.loads(line).get("item_id") == item_id:
                    return True
            except json.JSONDecodeError:
                continue
    return False


def mark_executed(item_id: str, summary: str = "") -> dict:
    """Record that an approved action was executed, so it never re-fires on replay."""
    record = {"item_id": item_id, "ts": _iso_utc(), "summary": summary[:200]}
    EXECUTIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with EXECUTIONS_PATH.open("a") as fh:
        fh.write(json.dumps(record) + "\n")
    return record


async def execute_item(item: dict, tools: list) -> dict:
    """Attempt to execute the tool referenced by an approval item.

    Honest scope note: gated escalations are usually OUTWARD tools (e.g.
    send_email, wire_transfer) that are NOT registered in the runner's tool
    list — the runner only registers reads and internal writes. Execution will
    therefore commonly report not-executable (``executed: False``) until real
    outward tools are added to the registry. This function is the ready
    mechanism for when they are.

    Never raises — all failures are returned as ``{"executed": False, ...}``.
    """
    from backend.services.tools import get_tool_by_name

    tool_name = item.get("tool", "")
    tool = get_tool_by_name(tools, tool_name)
    if tool is None:
        return {"executed": False, "reason": f"no such tool: {tool_name}"}
    try:
        result = await tool.handler(**(item.get("args") or {}))
        return {"executed": True, "result": result}
    except Exception as e:
        return {"executed": False, "reason": f"{type(e).__name__}: {e}"}
