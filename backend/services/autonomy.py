"""backend/services/autonomy.py — Pure tool-call classifier (Module A).

No I/O, no network.  Posture from env AGENT_AUTONOMY ∈ {cautious, proactive,
observe}; default: cautious.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

# ── Constants ──────────────────────────────────────────────────────────────────

# Persistent user-approved allowlist (same file written by agent_admin.autonomy_allow)
#
# Test override: set to a Path to pin the file location. When None (normal
# operation) it resolves inside the app data root — never a foreign dir.
_ALLOW_PATH_OVERRIDE: Path | None = None

# Fork-era location (~/.agentic-os/autonomy_allow.json) — read once for a
# one-time migration into the app data root, then never touched again.
_LEGACY_ALLOW_PATH: Path = Path.home() / ".agentic-os" / "autonomy_allow.json"

# Privileged self-mutating tools: ALWAYS gated regardless of posture or allowlist.
# They can never be promoted to auto-allow — the allowlist check is intentionally
# skipped for these tools (security boundary).
# code.task writes and executes arbitrary code on disk — always requires approval.
_ALWAYS_GATED: frozenset[str] = frozenset({
    "autonomy.allow",
    "loop.set_schedule",
    "code.task",
})

_DENY_SET: frozenset[str] = frozenset({
    "money.move", "auth.change", "data.delete", "vendor.sign",
})

# Matched against lowercased tool name
_DENY_KEYWORDS: tuple[str, ...] = (
    "delete", "destroy", "wipe", "remove", "transfer", "withdraw", "move_money",
)

_READ_SET: frozenset[str] = frozenset({
    "calendar.list_events",
    "inbox.list_open",
    "browser.search",
    "browser.fetch",
    "web.search",   # plain-HTTP search — read-only, works without camofox
    "web.fetch",    # plain-HTTP page read
    "academics.upcoming_deadlines",  # merged deadline view; no side effects
    "academics.student_profile",     # stage/track read; no side effects
    "vault.read",
    "system.audit",  # read-only self-audit; never writes or calls external services
    "consensus.ask",  # multi-model reasoning aid; no side effects (like browser.search)
})

# Anchored at start of (lowercased) tool name
_READ_PREFIX_RE = re.compile(
    r"^(list|get|read|search|fetch|summary|recent|status|view|query)"
)

_INTERNAL_SET: frozenset[str] = frozenset({
    "inbox.add", "inbox.mark_done",
    # Memory compaction rewrites distilled notes but archives (never deletes)
    # every removed item, so it is internal-reversible and safe to auto-run.
    "memory.compact",
    # vault.write is NOT here: writes to the vault (agent memory, notes,
    # schedules) require explicit human approval — gated via cautious
    # posture's default "unknown tool" fallthrough. See CLAUDE.md pinned
    # contract: vault.write must go to Approvals, not auto-run.
})

# Matched anywhere in lowercased tool name
_OUTWARD_KEYWORDS: tuple[str, ...] = (
    "send", "publish", "post", "email", "tweet", "share", "dm",
    "pay", "charge", "buy", "subscribe", "book", "schedule_send",
    "reminder", "create_event",
)

_VALID_POSTURES: frozenset[str] = frozenset({"cautious", "proactive", "observe"})


# ── Public dataclass ───────────────────────────────────────────────────────────

@dataclass
class GateDecision:
    decision: str     # "allow" | "gate" | "deny"
    reason: str
    tool: str
    side_effect: str  # "read" | "internal" | "outward" | "irreversible" | "unknown"


# ── Persistent allowlist ──────────────────────────────────────────────────────

def _allow_path() -> Path:
    """Resolve the autonomy allowlist file path.

    Order of resolution:
    1. _ALLOW_PATH_OVERRIDE (test hook)
    2. <data root>/data/autonomy_allow.json, via backend.vault.agentic_os_dir()

    One-time migration: if the new file doesn't exist yet but the legacy
    fork-era file does, copy it over (never delete the legacy file).
    """
    if _ALLOW_PATH_OVERRIDE is not None:
        return Path(_ALLOW_PATH_OVERRIDE)

    from backend.vault import agentic_os_dir

    path = agentic_os_dir() / "data" / "autonomy_allow.json"

    if not path.exists() and _LEGACY_ALLOW_PATH.exists():
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(_LEGACY_ALLOW_PATH.read_bytes())
        except OSError:
            pass

    return path


def _persistent_allowlist() -> set[str]:
    """Return the set of tools explicitly promoted to auto-allow by the user.

    Reads the JSON file best-effort.  Returns an empty set on any error so
    that a missing or corrupt file never blocks normal gate logic.
    """
    try:
        allow_path = _allow_path()
        if allow_path.exists():
            data = json.loads(allow_path.read_text())
            if isinstance(data, list):
                return set(data)
    except Exception:  # noqa: BLE001
        pass
    return set()


# ── Internal helpers ───────────────────────────────────────────────────────────

def _cautious_classify(tool: str) -> tuple[str, str, str]:
    """Return (decision, side_effect, reason) under cautious posture."""
    name = tool.lower()

    # Priority 1 — deny: explicit set or keyword in name
    if tool in _DENY_SET or any(kw in name for kw in _DENY_KEYWORDS):
        return (
            "deny",
            "irreversible",
            f"irreversible action '{tool}' is never self-authorized",
        )

    # Priority 2 — read → allow
    if (
        tool in _READ_SET
        or _READ_PREFIX_RE.match(name)
        or ".list_" in name
        or ".read" in name
    ):
        return (
            "allow",
            "read",
            f"read-only tool '{tool}' is safe to execute automatically",
        )

    # Priority 3 — internal-reversible → allow
    if tool in _INTERNAL_SET:
        return (
            "allow",
            "internal",
            f"internal-reversible tool '{tool}' runs automatically",
        )

    # Priority 4 — outward → gate
    if any(kw in name for kw in _OUTWARD_KEYWORDS):
        return (
            "gate",
            "outward",
            f"outward-facing tool '{tool}' requires human approval",
        )

    # Priority 5 — unknown → gate
    return (
        "gate",
        "unknown",
        f"unknown tool '{tool}' — cautious posture gates unrecognised calls",
    )


def _apply_posture(
    decision: str,
    side_effect: str,
    reason: str,
    posture: str,
) -> tuple[str, str]:
    """Apply posture override; return (decision, reason)."""
    if posture == "cautious":
        return decision, reason

    if posture == "observe":
        # Most conservative: deny stays deny; read stays allow; everything else → gate
        if side_effect == "irreversible":
            return "deny", reason
        if side_effect == "read":
            return "allow", reason
        return "gate", f"observe posture gates all non-read actions ({reason})"

    if posture == "proactive":
        # Deny-set stays deny; internal/outward/unknown → allow; read stays allow
        if side_effect == "irreversible":
            return "deny", reason
        if side_effect == "read":
            return "allow", reason
        return "allow", f"proactive posture auto-approves '{side_effect}' actions ({reason})"

    # Unrecognised posture — fall back to cautious behaviour
    return decision, reason


# ── Public API ─────────────────────────────────────────────────────────────────

def classify(
    tool: str,
    args: dict | None = None,  # noqa: ARG001 — reserved for future content-aware rules
    posture: str | None = None,
) -> GateDecision:
    """Classify a tool call under the current autonomy posture.

    Parameters
    ----------
    tool:
        Tool name, e.g. ``"calendar.list_events"``.
    args:
        Optional arguments (reserved; unused in current rule set).
    posture:
        Explicit posture override.  If *None*, reads the ``AGENT_AUTONOMY``
        environment variable; defaults to ``"cautious"``.
        Valid values: ``cautious | proactive | observe``.

    Returns
    -------
    GateDecision
        Populated with *decision*, *reason*, *tool*, and *side_effect*.
    """
    if posture is None:
        posture = os.environ.get("AGENT_AUTONOMY", "cautious")

    # Priority 0a — ALWAYS-GATED: privileged self-mutating tools.
    # These bypass posture, allowlist, and every other rule — each call
    # requires explicit user approval.  They cannot be added to the
    # persistent allowlist to escape this gate (security invariant).
    if tool in _ALWAYS_GATED:
        return GateDecision(
            decision="gate",
            reason=(
                f"'{tool}' is a privileged self-mutating tool — "
                "always requires user approval regardless of posture or allowlist"
            ),
            tool=tool,
            side_effect="outward",
        )

    # Priority 0b — persistent user-approved allowlist.
    # Tools explicitly promoted by the user via autonomy.allow skip the
    # normal gate logic and run automatically (internal side-effect).
    if tool in _persistent_allowlist():
        return GateDecision(
            decision="allow",
            reason="user-approved auto-allow",
            tool=tool,
            side_effect="internal",
        )

    decision, side_effect, reason = _cautious_classify(tool)
    decision, reason = _apply_posture(decision, side_effect, reason, posture)

    return GateDecision(
        decision=decision,
        reason=reason,
        tool=tool,
        side_effect=side_effect,
    )
