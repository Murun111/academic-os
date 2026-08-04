"""Agent memory write-back — Module B of Phase 2.

Files a finished agent run into the vault and consolidates it into the memory
index.  Reuses the Phase-1 vault tools (vault_read / vault_write) and the
Phase-1.1 memory consolidation engine.

Public interface:
    record_run(run, spec) -> dict

See: docs/specs/phase-2-coo-agent.md §Module B
"""
from __future__ import annotations

import logging
import re
import time

log = logging.getLogger(__name__)

# Agents whose output belongs in the shared daily note rather than an
# agent-specific log.
_DAILY_AGENTS: frozenset[str] = frozenset({"coo", "daily-brief"})

# Agents whose run output must NOT be consolidated back into memory — their
# reports are *about* memory/maintenance and would otherwise create recursive
# meta-noise in the spine they just cleaned.
_NO_CONSOLIDATE: frozenset[str] = frozenset({"memory-compact"})


# ── Helpers ───────────────────────────────────────────────────────────────────

def _note_path(agent: str, today: str) -> str:
    """Return the vault-relative path for the run's output note.

    Generated artifacts live under the canonical `output/` zone (raw → wiki →
    output). Daily-run agents share `output/daily/`; everyone else gets
    `output/<agent>/`."""
    if agent in _DAILY_AGENTS:
        return f"output/daily/{today}.md"
    return f"output/{agent}/{today}.md"


def _refresh_frontmatter(content: str, today: str, agent: str) -> str:
    """Ensure *content* has valid YAML frontmatter with last_updated: today.

    Rules (applied in order):
    1. Empty / missing → create fresh frontmatter + heading.
    2. Has last_updated: → update the date in-place (single substitution).
    3. Has frontmatter but no last_updated: → inject after the opening ---.
    4. No frontmatter at all → prepend minimal block.
    """
    if not content.strip():
        return f"---\nlast_updated: {today}\n---\n\n# {agent} log\n"

    if "last_updated:" in content:
        return re.sub(
            r"(last_updated:\s*)[\d-]+",
            f"last_updated: {today}",
            content,
            count=1,
        )

    if content.startswith("---"):
        # Inject last_updated right after the opening fence
        return re.sub(
            r"^---\n",
            f"---\nlast_updated: {today}\n",
            content,
            count=1,
        )

    # No frontmatter at all
    return f"---\nlast_updated: {today}\n---\n\n" + content


# ── Public interface ──────────────────────────────────────────────────────────

async def record_run(run, spec) -> dict:
    """File a finished run into the vault and consolidate it into memory.

    Parameters
    ----------
    run : AgentRun-compatible
        Attrs: .id, .agent, .result, .status (str | RunStatus enum),
               .trigger, .started_at
    spec : AgentSpec-compatible
        Attrs: .name, .description

    Returns
    -------
    dict
        Success: {"filed": True, "note": <relpath>, "memory": <dict>}
        Skip:    {"filed": False, "reason": "no result / not success"}
        Error:   {"filed": False, "reason": "<exception text>"}

    Never raises.
    """
    try:
        # ── 1. Guard: success + non-empty result ─────────────────────────────
        status = getattr(run, "status", "")
        ok = (
            str(status).endswith("success")
            or getattr(status, "value", "") == "success"
        )
        result = getattr(run, "result", None)
        if not ok or not result:
            return {"filed": False, "reason": "no result / not success"}

        # ── 2. Resolve target note path ──────────────────────────────────────
        today = time.strftime("%Y-%m-%d", time.gmtime())
        agent = str(getattr(run, "agent", "unknown"))
        trigger = str(getattr(run, "trigger", "") or "")
        relpath = _note_path(agent, today)

        # ── 3. Read existing note (creates fresh if missing) ─────────────────
        from backend.services.tools import vault_read, vault_write

        existing = await vault_read(relpath)
        raw = existing.get("content", "") if not existing.get("error") else ""
        content = _refresh_frontmatter(raw, today, agent)

        # ── 4. Append run section ─────────────────────────────────────────────
        hhmm = time.strftime("%H:%M", time.gmtime())
        content += f"\n## {hhmm} UTC — {agent} ({trigger})\n\n{result}\n"

        # ── 5. Write to vault (capture error; continue regardless) ────────────
        write_out = await vault_write(relpath, content)
        if write_out.get("error"):
            log.warning("vault_write error for %r: %s", relpath, write_out)

        # ── 6. Consolidate to memory (best-effort; swallow all errors) ────────
        mem_dict: dict = {}
        if agent in _NO_CONSOLIDATE:
            return {"filed": True, "note": relpath, "memory": {}}
        try:
            from backend.services import memory

            description = (
                getattr(spec, "description", "")
                or getattr(run, "trigger", "")
                or ""
            )
            thread = {
                "id": f"run-{run.id}",
                "messages": [
                    {"role": "user", "content": description},
                    {"role": "assistant", "content": result},
                ],
            }
            res = await memory.consolidate_thread(thread)
            mem_dict = res.to_dict() if hasattr(res, "to_dict") else {}
        except Exception as exc:
            log.warning("consolidate_thread failed (non-fatal): %s", exc)

        return {"filed": True, "note": relpath, "memory": mem_dict}

    except Exception as exc:
        log.error("record_run failed unexpectedly: %s: %s", type(exc).__name__, exc)
        return {"filed": False, "reason": str(exc)}
