"""Unified trajectory trace — blueprint §2.3 / roadmap B1.

One trajectory record per run, appended to ``data/traces/<YYYY-MM-DD>.jsonl`` by
folding the ``AgentRun`` the runner lifecycle produces. This is the canonical,
queryable episodic log that the eval harness (B2) and trajectory memory (B3)
will consume — replacing the scattered ``runs.jsonl`` / threads / events split.

Design notes:
- **Fold, don't duplicate.** A trace is derived purely from the finished
  ``AgentRun`` (single source); it holds no independent state that could drift.
- **Fail-open.** A trace error never disrupts or blocks a run — it is swallowed
  and printed, mirroring the critic gate. Disable entirely with ``AGENT_TRACE=0``
  (set across the test suite via ``conftest`` so runs stay hermetic).
- **Date-partitioned.** One file per day keeps reads cheap and pruning trivial.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from backend.vault import agentic_os_dir


def _enabled() -> bool:
    """Trace is on by default; ``AGENT_TRACE=0`` turns it off (tests, opt-out)."""
    return os.environ.get("AGENT_TRACE", "1") != "0"


def _args_hash(args: Any) -> str:
    """Stable short hash of tool-call arguments (no raw args stored — they may
    contain large or sensitive payloads; the hash is enough to dedup/compare)."""
    try:
        raw = json.dumps(args, sort_keys=True, default=str)
    except Exception:
        raw = str(args)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


def _summarize(value: Any, limit: int = 200) -> str:
    """Collapse a value to a single bounded line for the trace summary fields."""
    s = value if isinstance(value, str) else json.dumps(value, default=str)
    return s.strip().replace("\n", " ")[:limit]


def trajectory_from_run(run: Any, spec: Any = None) -> dict:
    """Fold an ``AgentRun`` (+ optional ``AgentSpec``) into one canonical record.

    Pure — does no I/O. The shape is the contract B2/B3 depend on, so keep it
    additive: new keys are fine, renames are breaking.
    """
    goal = ""
    if spec is not None:
        goal = (
            getattr(spec, "description", "")
            or getattr(spec, "name", "")
            or ""
        )

    tool_calls: list[dict] = []
    for tc in (getattr(run, "tool_calls", None) or []):
        tool_calls.append(
            {
                "name": tc.get("tool") or tc.get("name", ""),
                "args_hash": _args_hash(tc.get("args", tc.get("arguments"))),
                # The runner records tool output under "result_preview"
                # (agent_runner.py:494/524); fall back to "result" for callers
                # that fold a synthetic run.
                "result_summary": _summarize(
                    tc.get("result_preview") or tc.get("result", "")
                ),
            }
        )

    status = run.status.value if hasattr(run.status, "value") else str(run.status)
    finished_at = getattr(run, "finished_at", None)
    return {
        "run_id": getattr(run, "id", None),
        "agent": getattr(run, "agent", None),
        "goal": goal,
        "trigger": getattr(run, "trigger", None),
        "tool_calls": tool_calls,
        "critic": getattr(run, "critic", None),
        "outcome": status,
        "result_summary": _summarize(
            getattr(run, "result", None) or getattr(run, "error", None) or ""
        ),
        "timing_ms": round((getattr(run, "duration_seconds", 0.0) or 0.0) * 1000),
        "started_at": getattr(run, "started_at", None),
        "finished_at": finished_at,
        # Partition by the run's own finish time so a write-time latency spike
        # can't file a 23:59 run under the next day. Fall back to now() only
        # when the run never recorded a finish (should not happen post-lifecycle).
        "ts": finished_at or datetime.now().isoformat(timespec="microseconds"),
    }


class TraceStore:
    """Append-only, date-partitioned trajectory log under ``data/traces/``."""

    def __init__(self, base_dir: Optional[Path] = None):
        if base_dir is None:
            base_dir = agentic_os_dir() / "data" / "traces"
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _path_for(self, day: str) -> Path:
        return self.base_dir / f"{day}.jsonl"

    def append(self, record: dict) -> None:
        day = str(record.get("ts") or datetime.now().isoformat())[:10]
        path = self._path_for(day)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, default=str) + "\n")

    def _files(self) -> list[Path]:
        if not self.base_dir.exists():
            return []
        return sorted(self.base_dir.glob("*.jsonl"))

    def recent(self, n: int = 50) -> list[dict]:
        """Return up to the last *n* records across all day-files in time order.

        Tolerant of partial/corrupt lines: a malformed line is skipped rather
        than aborting the read (mirrors ``RunStore.list``)."""
        out: list[dict] = []
        for path in self._files():
            with path.open(encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        out.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue  # skip corrupt line, keep reading
        return out[-n:]

    def get(self, run_id: str) -> Optional[dict]:
        """Return the latest trajectory for *run_id*, or None.

        Scans newest-file-first and newest-line-first, returning on the first
        match — so it never loads the whole history into memory the way a
        ``recent(n=all)`` scan would."""
        for path in reversed(self._files()):
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except OSError:
                continue
            for line in reversed(lines):
                if not line.strip():
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if rec.get("run_id") == run_id:
                    return rec
        return None


_default_store: Optional[TraceStore] = None


def _store() -> TraceStore:
    global _default_store
    if _default_store is None:
        _default_store = TraceStore()
    return _default_store


def record_trace(run: Any, spec: Any = None) -> Optional[dict]:
    """Fold a finished run into a trajectory record and append it. Fail-open.

    Returns the record on success, or None when disabled (``AGENT_TRACE=0``) or
    on any error — a trace failure must never disrupt the run that produced it.
    """
    if not _enabled():
        return None
    try:
        record = trajectory_from_run(run, spec)
        _store().append(record)
        return record
    except Exception as e:  # never propagate into the run lifecycle
        print(f"[trace] record failed (ignored): {e}")
        return None
