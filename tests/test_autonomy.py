"""Tests for backend.services.autonomy — Module A gate classifier.

All tests are OFFLINE:
  - posture is passed explicitly, OR
  - env var is set/cleared via monkeypatch (no global env pollution).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.services.autonomy import GateDecision, classify


# ── Helpers ────────────────────────────────────────────────────────────────────

def _check(d: GateDecision, decision: str, side_effect: str) -> None:
    assert d.decision == decision, (
        f"expected decision={decision!r}, got {d.decision!r} for tool={d.tool!r}"
    )
    assert d.side_effect == side_effect, (
        f"expected side_effect={side_effect!r}, got {d.side_effect!r} for tool={d.tool!r}"
    )
    assert isinstance(d.reason, str) and d.reason, "reason must be a non-empty string"
    assert d.tool, "tool field must be populated"


# ── Read tools → allow / read ──────────────────────────────────────────────────

@pytest.mark.parametrize("tool", [
    "calendar.list_events",
    "inbox.list_open",
    "web.search",
    "web.fetch",
    "academics.upcoming_deadlines",
    "browser.search",
    "browser.fetch",
    "vault.read",
])
def test_explicit_read_set_allows(tool: str) -> None:
    _check(classify(tool, posture="cautious"), "allow", "read")


@pytest.mark.parametrize("tool", [
    "list_tasks",
    "get_config",
    "read_file",
    "search_contacts",
    "fetch_url",
    "summary_report",
    "recent_activity",
    "status_check",
    "view_profile",
    "query_db",
])
def test_read_prefix_allows(tool: str) -> None:
    _check(classify(tool, posture="cautious"), "allow", "read")


@pytest.mark.parametrize("tool", [
    "documents.list_all",
    "docs.list_recent",
    "service.read",
    "db.read_record",
])
def test_read_contains_list_or_read_allows(tool: str) -> None:
    _check(classify(tool, posture="cautious"), "allow", "read")


# ── Internal tools → allow / internal ─────────────────────────────────────────

@pytest.mark.parametrize("tool", [
    "inbox.add",
    "inbox.mark_done",
])
def test_internal_set_allows(tool: str) -> None:
    _check(classify(tool, posture="cautious"), "allow", "internal")


def test_vault_write_is_gated_not_internal() -> None:
    # Security fix (2026-08-14): vault.write was removed from _INTERNAL_SET so
    # an agent can't silently overwrite vault files (e.g. the autonomy
    # allowlist). It now falls through to unknown → gate under cautious.
    _check(classify("vault.write", posture="cautious"), "gate", "unknown")


# ── Deny set → deny / irreversible ────────────────────────────────────────────

@pytest.mark.parametrize("tool", [
    "money.move",
    "auth.change",
    "data.delete",
    "vendor.sign",
])
def test_explicit_deny_set_denies(tool: str) -> None:
    _check(classify(tool, posture="cautious"), "deny", "irreversible")


@pytest.mark.parametrize("tool", [
    "files.delete_all",
    "storage.destroy",
    "data.wipe",
    "records.remove",
    "account.transfer",
    "wallet.withdraw",
    "do_move_money",
])
def test_deny_keyword_patterns_deny(tool: str) -> None:
    _check(classify(tool, posture="cautious"), "deny", "irreversible")


# ── Outward tools → gate / outward ────────────────────────────────────────────

@pytest.mark.parametrize("tool", [
    "comms.send",
    "social.publish",
    "notifications.post",
    "mailer.email",
    "bot.tweet",
    "feed.share",
    "messaging.dm",
    "billing.pay",
    "stripe.charge",
    "shop.buy",
    "plan.subscribe",
    "reservations.book",
    "comms.schedule_send",
])
def test_outward_tools_gate(tool: str) -> None:
    _check(classify(tool, posture="cautious"), "gate", "outward")


# ── reminders.create → gate / outward ────────────────────────────────────────

def test_reminders_create_gates_as_outward() -> None:
    """reminders.create must be classified as outward → gate under cautious posture."""
    _check(classify("reminders.create", posture="cautious"), "gate", "outward")


# ── Unknown tool → gate / unknown ─────────────────────────────────────────────

def test_unknown_tool_gates() -> None:
    _check(classify("weird.frobnicate", posture="cautious"), "gate", "unknown")


def test_unknown_tool_with_args_gates() -> None:
    _check(classify("mystery.action", args={"x": 1}, posture="cautious"), "gate", "unknown")


# ── Posture: observe ──────────────────────────────────────────────────────────

def test_observe_internal_becomes_gate() -> None:
    _check(classify("inbox.add", posture="observe"), "gate", "internal")


def test_observe_outward_becomes_gate() -> None:
    _check(classify("comms.send", posture="observe"), "gate", "outward")


def test_observe_unknown_becomes_gate() -> None:
    _check(classify("weird.frobnicate", posture="observe"), "gate", "unknown")


def test_observe_read_still_allows() -> None:
    _check(classify("calendar.list_events", posture="observe"), "allow", "read")


def test_observe_deny_stays_deny() -> None:
    _check(classify("money.move", posture="observe"), "deny", "irreversible")


# ── Posture: proactive ────────────────────────────────────────────────────────

def test_proactive_internal_becomes_allow() -> None:
    _check(classify("inbox.add", posture="proactive"), "allow", "internal")


def test_proactive_outward_becomes_allow() -> None:
    _check(classify("comms.send", posture="proactive"), "allow", "outward")


def test_proactive_unknown_becomes_allow() -> None:
    _check(classify("weird.frobnicate", posture="proactive"), "allow", "unknown")


def test_proactive_read_stays_allow() -> None:
    _check(classify("browser.fetch", posture="proactive"), "allow", "read")


def test_proactive_deny_stays_deny() -> None:
    _check(classify("money.move", posture="proactive"), "deny", "irreversible")


def test_proactive_deny_keyword_stays_deny() -> None:
    _check(classify("files.delete_all", posture="proactive"), "deny", "irreversible")


# ── Env-var resolution (no global pollution) ──────────────────────────────────

def test_env_default_is_cautious(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AGENT_AUTONOMY", raising=False)
    # inbox.add is internal → allow under cautious (the env default)
    _check(classify("inbox.add"), "allow", "internal")


def test_env_cautious_explicit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENT_AUTONOMY", "cautious")
    _check(classify("inbox.add"), "allow", "internal")


def test_env_observe_gates_internal(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENT_AUTONOMY", "observe")
    _check(classify("inbox.add"), "gate", "internal")


def test_env_proactive_allows_outward(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENT_AUTONOMY", "proactive")
    _check(classify("comms.send"), "allow", "outward")


# ── Return-structure sanity ───────────────────────────────────────────────────

def test_gate_decision_tool_field_preserved() -> None:
    d = classify("money.move", posture="cautious")
    assert d.tool == "money.move"


def test_gate_decision_reason_nonempty_across_categories() -> None:
    for tool in ["money.move", "vault.read", "vault.write", "comms.send", "weird.x"]:
        d = classify(tool, posture="cautious")
        assert isinstance(d.reason, str) and d.reason, f"empty reason for {tool!r}"


def test_gate_decision_is_dataclass() -> None:
    d = classify("vault.read", posture="cautious")
    assert isinstance(d, GateDecision)
    assert hasattr(d, "decision")
    assert hasattr(d, "reason")
    assert hasattr(d, "tool")
    assert hasattr(d, "side_effect")


# ── system.audit → allow / read ───────────────────────────────────────────────

def test_system_audit_is_read_and_allowed() -> None:
    """system.audit must be allowed as a read-only tool under every posture."""
    _check(classify("system.audit", posture="cautious"), "allow", "read")
    _check(classify("system.audit", posture="observe"), "allow", "read")
    _check(classify("system.audit", posture="proactive"), "allow", "read")


# ── ALWAYS-GATED tools ────────────────────────────────────────────────────────

def test_loop_set_schedule_gates_cautious() -> None:
    """loop.set_schedule must always gate under cautious posture."""
    _check(classify("loop.set_schedule", posture="cautious"), "gate", "outward")


def test_loop_set_schedule_gates_proactive() -> None:
    """loop.set_schedule must gate even under proactive posture — posture never overrides."""
    _check(classify("loop.set_schedule", posture="proactive"), "gate", "outward")


def test_loop_set_schedule_gates_observe() -> None:
    _check(classify("loop.set_schedule", posture="observe"), "gate", "outward")


def test_autonomy_allow_gates_cautious() -> None:
    """autonomy.allow must always gate under cautious posture."""
    _check(classify("autonomy.allow", posture="cautious"), "gate", "outward")


def test_autonomy_allow_gates_proactive() -> None:
    """autonomy.allow must gate even under proactive posture."""
    _check(classify("autonomy.allow", posture="proactive"), "gate", "outward")


def test_autonomy_allow_gates_observe() -> None:
    _check(classify("autonomy.allow", posture="observe"), "gate", "outward")


# ── Persistent allowlist ──────────────────────────────────────────────────────

def test_persistent_allowlist_allows_tool(monkeypatch: pytest.MonkeyPatch) -> None:
    """A tool in the persistent allowlist must be auto-allowed (side_effect=internal)."""
    import backend.services.autonomy as autonomy_mod
    monkeypatch.setattr(autonomy_mod, "_persistent_allowlist", lambda: {"reminders.create"})
    _check(classify("reminders.create", posture="cautious"), "allow", "internal")


def test_persistent_allowlist_allows_tool_under_observe(monkeypatch: pytest.MonkeyPatch) -> None:
    """An allowlisted tool bypasses posture — allowed even under observe."""
    import backend.services.autonomy as autonomy_mod
    monkeypatch.setattr(autonomy_mod, "_persistent_allowlist", lambda: {"some.tool"})
    _check(classify("some.tool", posture="observe"), "allow", "internal")


def test_always_gated_wins_over_allowlist(monkeypatch: pytest.MonkeyPatch) -> None:
    """Even if autonomy.allow is added to the allowlist, it must remain gated."""
    import backend.services.autonomy as autonomy_mod
    monkeypatch.setattr(autonomy_mod, "_persistent_allowlist", lambda: {"autonomy.allow"})
    _check(classify("autonomy.allow", posture="cautious"), "gate", "outward")


def test_always_gated_wins_over_allowlist_proactive(monkeypatch: pytest.MonkeyPatch) -> None:
    """loop.set_schedule in allowlist under proactive must still gate."""
    import backend.services.autonomy as autonomy_mod
    monkeypatch.setattr(autonomy_mod, "_persistent_allowlist", lambda: {"loop.set_schedule"})
    _check(classify("loop.set_schedule", posture="proactive"), "gate", "outward")


# ── code.task → gate / outward ────────────────────────────────────────────────

def test_code_task_gates_as_outward_cautious() -> None:
    """code.task must always gate (outward) — it writes + executes code on disk."""
    _check(classify("code.task", posture="cautious"), "gate", "outward")


def test_code_task_gates_as_outward_proactive() -> None:
    """code.task must gate even under proactive posture — always-gated invariant."""
    _check(classify("code.task", posture="proactive"), "gate", "outward")


def test_code_task_gates_as_outward_observe() -> None:
    _check(classify("code.task", posture="observe"), "gate", "outward")


# ── _allow_path: one-time migration from the legacy fork location ─────────────

def test_allow_path_migrates_legacy_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When no new-location file exists yet but the legacy ~/.agentic-os one
    does, _allow_path() copies it into the data root and leaves the legacy
    file in place."""
    import backend.services.autonomy as autonomy_mod

    data_root = tmp_path / "data-root"
    legacy = tmp_path / "home" / ".agentic-os" / "autonomy_allow.json"
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text(json.dumps(["legacy.tool"]))

    monkeypatch.setattr("backend.vault.resolve_vault_path", lambda: data_root)
    monkeypatch.setattr(autonomy_mod, "_LEGACY_ALLOW_PATH", legacy)

    resolved = autonomy_mod._allow_path()

    assert resolved == data_root / "data" / "autonomy_allow.json"
    assert resolved.exists()
    assert json.loads(resolved.read_text()) == ["legacy.tool"]
    assert legacy.exists()  # never deleted


def test_persistent_allowlist_reads_migrated_legacy_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """End-to-end: _persistent_allowlist() picks up tools from a legacy file
    that has never been copied to the new location yet."""
    import backend.services.autonomy as autonomy_mod

    data_root = tmp_path / "data-root"
    legacy = tmp_path / "home" / ".agentic-os" / "autonomy_allow.json"
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text(json.dumps(["legacy.tool"]))

    monkeypatch.setattr("backend.vault.resolve_vault_path", lambda: data_root)
    monkeypatch.setattr(autonomy_mod, "_LEGACY_ALLOW_PATH", legacy)

    assert autonomy_mod._persistent_allowlist() == {"legacy.tool"}
