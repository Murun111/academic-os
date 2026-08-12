"""Trajectory memory — blueprint §2.4 / roadmap B3. Retrieval-as-learning.

The single highest-ROI "learning" step that needs no training: when a run passes
the critic, store its trajectory (goal → approach → outcome) with an embedding;
when a new task arrives, retrieve the top-k most similar *past successful*
trajectories and inject them as few-shot guidance. The model conditions on what
worked before — a growing private corpus of your own successes.

This is a **parallel index** (its own SQLite table), deliberately separate from
the semantic fact-memory (`memory_index`) so trajectories never pollute fact
recall — but it *reuses* that module's Ollama `embed()` and `_cosine()` rather
than reimplementing them.

Fully opt-in behind ``AGENT_TRAJECTORY_MEMORY`` (default off): when off, both
storing and retrieval are no-ops, so the runner is unaffected until you enable
it. Every path is fail-open — trajectory memory must never disrupt a run.
"""
from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Any, Optional

from backend.services.memory_index import _cosine, embed

# Test override: set to a Path to pin the DB location. When None (normal
# operation) the DB lives inside the app data root — never a foreign dir.
DB_PATH: Optional[Path] = None


def _default_db_path() -> Path:
    if DB_PATH is not None:
        return Path(DB_PATH)
    from backend.vault import agentic_os_dir
    return agentic_os_dir() / "data" / "memory" / "trajectories.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS trajectories (
    run_id    TEXT PRIMARY KEY,
    agent     TEXT NOT NULL DEFAULT '',
    goal      TEXT NOT NULL DEFAULT '',
    approach  TEXT NOT NULL DEFAULT '',
    outcome   TEXT NOT NULL DEFAULT '',
    ts        TEXT NOT NULL DEFAULT '',
    embedding TEXT
);
"""


def _enabled() -> bool:
    """Opt-in: off by default. Set AGENT_TRAJECTORY_MEMORY=1 to turn on."""
    return os.environ.get("AGENT_TRAJECTORY_MEMORY", "0") != "0"


def _critic_passed(run: Any) -> bool:
    """Only runs the critic actively graduated become few-shot exemplars.

    A disabled critic (`AGENT_CRITIC=0`) returns verdict "pass" with reason
    "critic disabled" — that is NOT a real verification, so it must not graduate
    unreviewed runs into the corpus. (Coupled to critic.py's disabled-reason
    string; keep in sync.)"""
    critic = getattr(run, "critic", None)
    if not critic or critic.get("verdict") != "pass":
        return False
    return critic.get("reason", "") != "critic disabled"


def _approach_of(run: Any) -> str:
    """A compact description of how the run proceeded — the tool sequence."""
    names = [
        (tc.get("tool") or tc.get("name", ""))
        for tc in (getattr(run, "tool_calls", None) or [])
    ]
    names = [n for n in names if n]
    return " → ".join(names) if names else "(direct answer, no tools)"


class TrajectoryStore:
    """SQLite store of critic-passed run trajectories with embeddings."""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = Path(db_path) if db_path else _default_db_path()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript(_SCHEMA)

    def add(self, run_id: str, agent: str, goal: str, approach: str,
            outcome: str, ts: str, embedding: Optional[list[float]]) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """INSERT OR REPLACE INTO trajectories
                   (run_id, agent, goal, approach, outcome, ts, embedding)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (run_id, agent, goal, approach, outcome, ts,
                 json.dumps(embedding) if embedding is not None else None),
            )

    def _rows(self) -> list[sqlite3.Row]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            return conn.execute("SELECT * FROM trajectories").fetchall()

    def nearest(self, query_vec: list[float], k: int,
                agent: Optional[str] = None) -> list[dict]:
        scored: list[tuple[float, dict]] = []
        for row in self._rows():
            if agent is not None and row["agent"] != agent:
                continue  # an agent retrieves only its own past successes
            vec = json.loads(row["embedding"]) if row["embedding"] else None
            if vec is None:
                continue
            scored.append((_cosine(query_vec, vec), dict(row)))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [r for _, r in scored[:k]]


_default_store: Optional[TrajectoryStore] = None


def _store() -> TrajectoryStore:
    global _default_store
    if _default_store is None:
        _default_store = TrajectoryStore()
    return _default_store


async def store_trajectory(run: Any, spec: Any = None) -> bool:
    """Graduate a critic-passed successful run into trajectory memory. Fail-open.

    Returns True when stored, False when disabled / not eligible / on any error.
    """
    if not _enabled():
        return False
    try:
        status = run.status.value if hasattr(run.status, "value") else str(run.status)
        if status != "success" or not _critic_passed(run):
            return False
        goal = ""
        if spec is not None:
            goal = getattr(spec, "description", "") or getattr(spec, "name", "") or ""
        approach = _approach_of(run)
        outcome = (getattr(run, "result", None) or "")[:500]
        # Embed the GOAL only — retrieval pivots on the goal, so store and query
        # must use identical text or the vectors land in different regions and
        # similarity is noisy. (approach/outcome stay as stored metadata.)
        vec = await embed(goal)
        _store().add(
            run_id=getattr(run, "id", ""),
            agent=getattr(run, "agent", ""),
            goal=goal, approach=approach, outcome=outcome,
            ts=getattr(run, "finished_at", "") or "",
            embedding=vec,
        )
        return True
    except Exception as e:  # never disrupt the run
        print(f"[trajectory] store failed (ignored): {e}")
        return False


async def retrieve(goal: str, k: int = 3,
                   agent: Optional[str] = None) -> list[dict]:
    """Top-k past successful trajectories most similar to *goal*. Fail-open → [].

    *agent*, when given, scopes retrieval to that agent's own trajectories."""
    if not _enabled() or not (goal or "").strip():
        return []
    try:
        vec = await embed(goal)
        if vec is None:
            return []
        return _store().nearest(vec, k, agent=agent)
    except Exception as e:
        print(f"[trajectory] retrieve failed (ignored): {e}")
        return []


def format_fewshot(trajectories: list[dict]) -> str:
    """Render retrieved trajectories as a compact few-shot guidance block.

    Deliberately injects only the *goal* and *tool approach* — NOT the raw
    `outcome` text. The outcome is unsanitized prior model/tool output; replaying
    it into a future system prompt would be a prompt-injection relay (a past
    output containing "ignore previous instructions" would be obeyed). Goal +
    approach give the model the routing signal without that risk; the full
    outcome stays in the DB for debugging only."""
    if not trajectories:
        return ""
    lines = [
        "Here are similar tasks you handled successfully before — use them as "
        "guidance for your approach, not as answers to copy:",
    ]
    for i, t in enumerate(trajectories, 1):
        lines.append(
            f"{i}. Goal: {t.get('goal', '')}\n"
            f"   Approach used: {t.get('approach', '')}"
        )
    return "\n".join(lines)


async def maybe_inject(goal: str, k: int = 3, agent: Optional[str] = None) -> str:
    """Convenience: retrieve + format in one call. "" when disabled or empty."""
    return format_fewshot(await retrieve(goal, k=k, agent=agent))
