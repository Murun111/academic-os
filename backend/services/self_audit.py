"""Self-audit engine — mines the OS's own run history for improvement signals.

Exported
--------
audit(run_records, specs, decisions) -> dict
    Returns a structured observations dict ready to be consumed by agents
    or surfaced in a dashboard.  All sub-computations are guarded so a
    single malformed record can never crash the whole audit.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import Any

_FINAL_STATUSES = frozenset({"success", "failed", "timeout", "cancelled"})


def _safe_get(obj: Any, attr: str, default: Any = None) -> Any:
    """Get attribute (dataclass/namespace) or dict key; never raises."""
    try:
        if hasattr(obj, attr):
            return getattr(obj, attr)
        return obj.get(attr, default)  # type: ignore[union-attr]
    except Exception:
        return default


def _dedupe_runs(raw: list) -> list[dict]:
    """Collapse RUNNING + final records for the same run id.

    Preference order (highest wins):
      1. final status (success/failed/timeout/cancelled) over 'running'
      2. higher iteration count when both are in the same category
    """
    by_id: dict[str, dict] = {}
    for run in raw:
        try:
            rid = run.get("id", "")
            if not rid:
                continue
            existing = by_id.get(rid)
            if existing is None:
                by_id[rid] = run
                continue
            curr_final = run.get("status", "") in _FINAL_STATUSES
            ex_final = existing.get("status", "") in _FINAL_STATUSES
            if curr_final and not ex_final:
                by_id[rid] = run
            elif curr_final == ex_final:
                if run.get("iterations", 0) >= existing.get("iterations", 0):
                    by_id[rid] = run
        except Exception:
            pass
    return list(by_id.values())


def audit(
    run_records: list | None = None,
    specs: list | None = None,
    decisions: list | None = None,
) -> dict:
    """Mine the OS's own run history for improvement signals.

    Parameters
    ----------
    run_records:
        List of run dicts (RunStore format).  *None* → loaded from disk.
    specs:
        List of AgentSpec objects.  *None* → loaded from disk.
    decisions:
        List of approval decision dicts.  *None* → loaded from disk.

    Returns
    -------
    dict with keys: window, agents, tools, scheduling, autonomy, friction.
    """
    # ── Load from disk if not injected ────────────────────────────────────────
    if run_records is None:
        try:
            from backend.services.agent_runner import RunStore
            run_records = RunStore().list(limit=500)
        except Exception:
            run_records = []

    if specs is None:
        try:
            from backend.services.agent_loader import AgentLoader
            from backend.vault import agentic_os_dir
            specs = AgentLoader(agentic_os_dir() / "agents").list_all()
        except Exception:
            specs = []

    if decisions is None:
        try:
            from backend.services import approvals
            decisions = approvals.list_decisions()
        except Exception:
            decisions = []

    run_records = list(run_records or [])
    specs = list(specs or [])
    decisions = list(decisions or [])

    runs = _dedupe_runs(run_records)

    # Build spec lookup {name: spec}
    spec_map: dict[str, Any] = {}
    for spec in specs:
        try:
            name = _safe_get(spec, "name", "")
            if name:
                spec_map[str(name)] = spec
        except Exception:
            pass

    # ── Agent-level stats ─────────────────────────────────────────────────────
    agent_runs: dict[str, list[dict]] = defaultdict(list)
    for run in runs:
        try:
            agent = run.get("agent", "")
            if agent:
                agent_runs[str(agent)].append(run)
        except Exception:
            pass

    # Include agents that have specs but no runs
    for spec in specs:
        try:
            name = str(_safe_get(spec, "name", "") or "")
            if name and name not in agent_runs:
                agent_runs[name] = []
        except Exception:
            pass

    agent_stats: list[dict] = []
    for agent_name, agent_run_list in agent_runs.items():
        try:
            total = len(agent_run_list)
            successes = sum(1 for r in agent_run_list if r.get("status") == "success")
            failures = sum(
                1 for r in agent_run_list if r.get("status") in ("failed", "timeout")
            )
            success_rate = (successes / total) if total > 0 else None
            avg_iter = (
                sum(r.get("iterations", 0) for r in agent_run_list) / total
            ) if total > 0 else 0.0
            escalation_count = sum(
                len(r.get("escalations", [])) for r in agent_run_list
            )
            last_status = agent_run_list[-1].get("status") if agent_run_list else None
            spec = spec_map.get(agent_name)
            scheduled = bool(_safe_get(spec, "schedule")) if spec is not None else False
            agent_stats.append({
                "name": agent_name,
                "runs": total,
                "successes": successes,
                "failures": failures,
                "success_rate": round(success_rate, 4) if success_rate is not None else None,
                "avg_iterations": round(avg_iter, 2),
                "escalations": escalation_count,
                "scheduled": scheduled,
                "last_status": last_status,
            })
        except Exception:
            pass

    agent_stats.sort(key=lambda x: x.get("runs", 0), reverse=True)

    # ── Tool stats ────────────────────────────────────────────────────────────
    tool_error_count: Counter = Counter()
    tool_gate_count: Counter = Counter()

    for run in runs:
        try:
            for tc in run.get("tool_calls", []):
                tool = tc.get("tool", "")
                if not tool:
                    continue
                preview = str(tc.get("result_preview", "")).lower()
                gate = str(tc.get("gate", "")).lower()
                if "error" in preview or gate in ("deny", "gate"):
                    tool_error_count[tool] += 1
            for esc in run.get("escalations", []):
                tool = esc.get("tool", "")
                if tool:
                    tool_gate_count[tool] += 1
        except Exception:
            pass

    most_errored = [{"tool": t, "errors": c} for t, c in tool_error_count.most_common(5)]
    most_gated = [{"tool": t, "count": c} for t, c in tool_gate_count.most_common(5)]

    # ── Scheduling signals ────────────────────────────────────────────────────
    idle_scheduled: list[str] = []
    manual_repeat: list[str] = []
    for stat in agent_stats:
        try:
            if stat["scheduled"] and stat["successes"] == 0:
                idle_scheduled.append(stat["name"])
            if not stat["scheduled"] and stat["runs"] >= 3:
                manual_repeat.append(stat["name"])
        except Exception:
            pass

    # ── Autonomy signals ──────────────────────────────────────────────────────
    # Build (run_id, idx) → tool lookup from all escalations
    esc_lookup: dict[tuple[str, int], str] = {}
    for run in runs:
        try:
            for idx, esc in enumerate(run.get("escalations", [])):
                tool = esc.get("tool", "")
                if tool:
                    esc_lookup[(run.get("id", ""), idx)] = tool
        except Exception:
            pass

    tool_approved: Counter = Counter()
    tool_dismissed: Counter = Counter()

    for dec in decisions:
        try:
            item_id = dec.get("item_id", "")
            decision_val = dec.get("decision", "")
            parts = item_id.rsplit(":", 1)
            if len(parts) != 2:
                continue
            run_id, idx_str = parts
            try:
                idx = int(idx_str)
            except ValueError:
                continue
            tool = esc_lookup.get((run_id, idx))
            if not tool:
                continue
            if decision_val == "approved":
                tool_approved[tool] += 1
            elif decision_val == "dismissed":
                tool_dismissed[tool] += 1
        except Exception:
            pass

    always_approved = [
        t for t in tool_approved
        if tool_approved[t] >= 2 and tool_dismissed.get(t, 0) == 0
    ]
    always_dismissed = [
        t for t in tool_dismissed
        if tool_dismissed[t] >= 2 and tool_approved.get(t, 0) == 0
    ]

    # ── Friction: recurring error strings ────────────────────────────────────
    error_count: Counter = Counter()
    for run in runs:
        try:
            err = run.get("error")
            if not err:
                continue
            normalized = re.sub(r"\b[0-9a-f]{8,}\b", "<id>", str(err).lower())
            normalized = re.sub(r"\d+", "N", normalized).strip()
            if normalized:
                error_count[normalized] += 1
        except Exception:
            pass

    friction = [err for err, cnt in error_count.most_common(5) if cnt >= 2]

    return {
        "window": {
            "runs": len(runs),
            "agents": len(agent_stats),
            "decisions": len(decisions),
        },
        "agents": agent_stats,
        "tools": {
            "most_errored": most_errored,
            "most_gated": most_gated,
        },
        "scheduling": {
            "idle_scheduled": idle_scheduled,
            "manual_repeat": manual_repeat,
        },
        "autonomy": {
            "always_approved": always_approved,
            "always_dismissed": always_dismissed,
        },
        "friction": friction,
    }
