"""Tests for backend.services.agent_admin — OFFLINE.

All vault I/O is redirected to tmp_path via monkeypatching
backend.vault.resolve_vault_path.  The autonomy allowlist file is
redirected by patching admin_mod._ALLOW_FILE.  No real iCloud or
home-directory files are touched.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import backend.services.agent_admin as admin_mod


# ── Fixture spec content ───────────────────────────────────────────────────────

FIXTURE_SPEC = """\
---
name: coo
schedule: "0 9 * * 1"
enabled: true
---

# COO Agent

Produces the daily brief.
"""

FIXTURE_SPEC_NO_SCHEDULE = """\
---
name: coo
enabled: true
---

# COO Agent

No schedule yet.
"""


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_spec(vault: Path, agent: str, content: str) -> Path:
    spec_dir = vault / "Agentic OS" / "agents"
    spec_dir.mkdir(parents=True, exist_ok=True)
    p = spec_dir / f"{agent}.md"
    p.write_text(content)
    return p


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture
def tmp_vault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect all vault I/O to tmp_path."""
    monkeypatch.setattr("backend.vault.resolve_vault_path", lambda: tmp_path)
    return tmp_path


@pytest.fixture
def tmp_allow(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect the allowlist JSON file to a tmp location."""
    allow_path = tmp_path / "home" / ".agentic-os" / "autonomy_allow.json"
    monkeypatch.setattr(admin_mod, "_ALLOW_FILE", allow_path)
    return allow_path


# ── set_schedule: update existing schedule ─────────────────────────────────────

@pytest.mark.asyncio
async def test_set_schedule_updates_existing_cron(tmp_vault: Path) -> None:
    _make_spec(tmp_vault, "coo", FIXTURE_SPEC)
    result = await admin_mod.set_schedule("coo", schedule="0 8 * * *")
    assert result["ok"] is True
    content = (tmp_vault / "Agentic OS" / "agents" / "coo.md").read_text()
    assert 'schedule: "0 8 * * *"' in content
    # original schedule should be gone
    assert '"0 9 * * 1"' not in content


# ── set_schedule: empty schedule removes the line ─────────────────────────────

@pytest.mark.asyncio
async def test_set_schedule_empty_removes_schedule_line(tmp_vault: Path) -> None:
    _make_spec(tmp_vault, "coo", FIXTURE_SPEC)
    result = await admin_mod.set_schedule("coo", schedule="")
    assert result["ok"] is True
    content = (tmp_vault / "Agentic OS" / "agents" / "coo.md").read_text()
    assert "schedule:" not in content


# ── set_schedule: set enabled: false ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_set_schedule_sets_enabled_false(tmp_vault: Path) -> None:
    _make_spec(tmp_vault, "coo", FIXTURE_SPEC)
    result = await admin_mod.set_schedule("coo", enabled=False)
    assert result["ok"] is True
    content = (tmp_vault / "Agentic OS" / "agents" / "coo.md").read_text()
    assert "enabled: false" in content


# ── set_schedule: insert enabled when absent ──────────────────────────────────

@pytest.mark.asyncio
async def test_set_schedule_inserts_enabled_when_absent(tmp_vault: Path) -> None:
    """enabled: should be added to frontmatter when not present."""
    spec = "---\nname: coo\n---\n\n# body\n"
    _make_spec(tmp_vault, "coo", spec)
    result = await admin_mod.set_schedule("coo", enabled=True)
    assert result["ok"] is True
    content = (tmp_vault / "Agentic OS" / "agents" / "coo.md").read_text()
    assert "enabled: true" in content


# ── set_schedule: missing agent ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_set_schedule_missing_agent_returns_error(tmp_vault: Path) -> None:
    # Agents dir exists but the file does not
    (tmp_vault / "Agentic OS" / "agents").mkdir(parents=True, exist_ok=True)
    result = await admin_mod.set_schedule("ghost_agent")
    assert result["ok"] is False
    assert result["error"] == "agent not found"


# ── set_schedule: body is preserved unchanged ─────────────────────────────────

@pytest.mark.asyncio
async def test_set_schedule_preserves_body(tmp_vault: Path) -> None:
    _make_spec(tmp_vault, "coo", FIXTURE_SPEC)
    await admin_mod.set_schedule("coo", schedule="0 8 * * *")
    content = (tmp_vault / "Agentic OS" / "agents" / "coo.md").read_text()
    assert "# COO Agent" in content
    assert "Produces the daily brief." in content


# ── autonomy_allow: creates file and appends ──────────────────────────────────

@pytest.mark.asyncio
async def test_autonomy_allow_creates_file_and_appends(tmp_allow: Path) -> None:
    result = await admin_mod.autonomy_allow("reminders.create")
    assert result["ok"] is True
    assert "reminders.create" in result["allowlist"]
    assert tmp_allow.exists()
    data = json.loads(tmp_allow.read_text())
    assert "reminders.create" in data


# ── autonomy_allow: deduplication ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_autonomy_allow_dedupes(tmp_allow: Path) -> None:
    await admin_mod.autonomy_allow("reminders.create")
    await admin_mod.autonomy_allow("reminders.create")
    result = await admin_mod.autonomy_allow("reminders.create")
    assert result["ok"] is True
    assert result["allowlist"].count("reminders.create") == 1


# ── autonomy_allow: multiple distinct tools ───────────────────────────────────

@pytest.mark.asyncio
async def test_autonomy_allow_accumulates_distinct_tools(tmp_allow: Path) -> None:
    await admin_mod.autonomy_allow("tool.a")
    result = await admin_mod.autonomy_allow("tool.b")
    assert result["ok"] is True
    assert "tool.a" in result["allowlist"]
    assert "tool.b" in result["allowlist"]
