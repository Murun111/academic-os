"""backend/services/agent_admin.py — Agent spec mutations (apply-tools).

Public interface:
    set_schedule(agent, schedule, enabled) -> dict
    autonomy_allow(tool) -> dict

These are the implementations behind the two GATED tools registered in
tools.py.  Both functions are offline-testable — vault I/O flows through the
existing vault_read / vault_write helpers, so tests only need to redirect
resolve_vault_path.
"""
from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path

log = logging.getLogger(__name__)

# Persistent allowlist — same file read by autonomy._persistent_allowlist()
#
# Test override: set to a Path to pin the file location. When None (normal
# operation) it resolves inside the app data root — never a foreign dir.
_ALLOW_FILE_OVERRIDE: Path | None = None

# Fork-era location (~/.agentic-os/autonomy_allow.json) — read once for a
# one-time migration into the app data root, then never touched again.
_LEGACY_ALLOW_FILE: Path = Path.home() / ".agentic-os" / "autonomy_allow.json"


def _allow_file() -> Path:
    """Resolve the autonomy allowlist file path.

    Order of resolution:
    1. _ALLOW_FILE_OVERRIDE (test hook)
    2. <data root>/data/autonomy_allow.json, via backend.vault.agentic_os_dir()

    One-time migration: if the new file doesn't exist yet but the legacy
    fork-era file does, copy it over (never delete the legacy file).
    """
    if _ALLOW_FILE_OVERRIDE is not None:
        return Path(_ALLOW_FILE_OVERRIDE)

    from backend.vault import agentic_os_dir

    path = agentic_os_dir() / "data" / "autonomy_allow.json"

    if not path.exists() and _LEGACY_ALLOW_FILE.exists():
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(_LEGACY_ALLOW_FILE.read_bytes())
        except OSError:
            pass  # best-effort — normal write path below still creates the file

    return path

# Matches the YAML frontmatter block (opening --- through the closing ---)
_FM_RE = re.compile(r"^---\n(.*?)^---[ \t]*\n?", re.DOTALL | re.MULTILINE)


# ── Frontmatter helper ─────────────────────────────────────────────────────────

def _edit_frontmatter(content: str, schedule: str | None, enabled: bool | None) -> str:
    """Edit schedule and/or enabled inside the YAML frontmatter.

    The markdown body (everything after the closing ---) is never touched.
    If the file has no frontmatter block the content is returned unchanged.
    """
    m = _FM_RE.match(content)
    if not m:
        return content  # no frontmatter — no-op

    fm_body = m.group(1)            # YAML lines between the fences
    rest = content[m.end():]        # body after the closing ---

    if schedule is not None:
        if schedule == "":
            # Remove the schedule line entirely (disables the cron)
            fm_body = re.sub(r"^schedule:.*\n?", "", fm_body, flags=re.MULTILINE)
        else:
            if re.search(r"^schedule:", fm_body, re.MULTILINE):
                fm_body = re.sub(
                    r"^schedule:.*$",
                    f'schedule: "{schedule}"',
                    fm_body,
                    count=1,
                    flags=re.MULTILINE,
                )
            else:
                if not fm_body.endswith("\n"):
                    fm_body += "\n"
                fm_body += f'schedule: "{schedule}"\n'

    if enabled is not None:
        val = "true" if enabled else "false"
        if re.search(r"^enabled:", fm_body, re.MULTILINE):
            fm_body = re.sub(
                r"^enabled:.*$",
                f"enabled: {val}",
                fm_body,
                count=1,
                flags=re.MULTILINE,
            )
        else:
            if not fm_body.endswith("\n"):
                fm_body += "\n"
            fm_body += f"enabled: {val}\n"

    # Safety: ensure fm_body ends with a newline before the closing fence
    if not fm_body.endswith("\n"):
        fm_body += "\n"

    return f"---\n{fm_body}---\n{rest}"


# ── Public interface ───────────────────────────────────────────────────────────

async def set_schedule(
    agent: str,
    schedule: str | None = None,
    enabled: bool | None = None,
) -> dict:
    """Reschedule or enable/disable an agent by editing its spec frontmatter.

    Parameters
    ----------
    agent:
        Agent name (matches the spec filename under Agentic OS/agents/, no .md).
    schedule:
        Cron string to set.  Empty string → remove the schedule line (disables
        cron without touching enabled:).  None → leave unchanged.
    enabled:
        True/False to set the enabled flag.  None → leave unchanged.

    Returns {"ok": True, ...} on success; {"ok": False, "error": ...} on any
    failure.  Never raises.
    """
    try:
        from backend.services.tools import vault_read, vault_write

        relpath = f"Agentic OS/agents/{agent}.md"
        result = await vault_read(relpath)

        if result.get("error") == "not_found":
            return {"ok": False, "error": "agent not found"}
        if result.get("error"):
            return {"ok": False, "error": result["error"]}

        updated = _edit_frontmatter(result.get("content", ""), schedule, enabled)

        write_result = await vault_write(relpath, updated)
        if write_result.get("error"):
            return {"ok": False, "error": write_result["error"]}

        return {"ok": True, "agent": agent, "schedule": schedule, "enabled": enabled}

    except Exception as exc:  # pragma: no cover
        log.error("set_schedule failed: %s: %s", type(exc).__name__, exc)
        return {"ok": False, "error": str(exc)}


async def autonomy_allow(tool: str) -> dict:
    """Append *tool* to the persistent autonomy allowlist (idempotent).

    Creates the JSON file and its parent directory if absent.  Returns the
    current full allowlist.  Never raises.
    """
    try:
        allow_path = _allow_file()
        allow_path.parent.mkdir(parents=True, exist_ok=True)

        if allow_path.exists():
            try:
                current: list[str] = json.loads(allow_path.read_text())
                if not isinstance(current, list):
                    current = []
            except (json.JSONDecodeError, OSError):
                current = []
        else:
            current = []

        if tool not in current:
            current.append(tool)
            tmp = allow_path.with_name(f".{allow_path.name}.tmp")
            tmp.write_text(json.dumps(current))
            os.replace(tmp, allow_path)

        return {"ok": True, "allowlist": current}

    except Exception as exc:  # pragma: no cover
        log.error("autonomy_allow failed: %s: %s", type(exc).__name__, exc)
        return {"ok": False, "error": str(exc)}
