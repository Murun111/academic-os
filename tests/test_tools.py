"""Tests for backend.services.tools — tool registry.

Tests the tool definitions, the Ollama schema conversion, and
that handlers are bound to the right services.
"""
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from backend.services import tools as t_mod
from backend.services.tools import (
    ToolSpec,
    build_tools,
    get_tool_by_name,
    tools_to_ollama_schema,
)
from backend.vault import resolve_vault_path


def test_build_tools_empty_when_no_services():
    tools = build_tools()
    # Even with no services, vault.read and vault.write are available.
    names = {t.name for t in tools}
    assert "vault.read" in names
    assert "vault.write" in names


def test_build_tools_calendar_present():
    cal = MagicMock()
    tools = build_tools(calendar_service=cal)
    names = {t.name for t in tools}
    assert "calendar.list_events" in names


def test_build_tools_inbox_present():
    inbox = MagicMock()
    tools = build_tools(inbox_service=inbox)
    names = {t.name for t in tools}
    assert "inbox.list_open" in names
    assert "inbox.add" in names
    assert "inbox.mark_done" in names


def test_build_tools_browser_present():
    browser = MagicMock()
    tools = build_tools(browser_service=browser)
    names = {t.name for t in tools}
    assert "browser.search" in names
    assert "browser.fetch" in names


def test_build_tools_full_set():
    """All services present → all tools present."""
    tools = build_tools(
        calendar_service=MagicMock(),
        inbox_service=MagicMock(),
        browser_service=MagicMock(),
    )
    names = {t.name for t in tools}
    assert names == {
        "web.search",
        "web.fetch",
        "academics.upcoming_deadlines",
        "academics.add_application",
        "calendar.list_events",
        "inbox.list_open",
        "inbox.add",
        "inbox.mark_done",
        "browser.search",
        "browser.fetch",
        "vault.read",
        "vault.write",
        "reminders.create",
        "system.audit",
        "memory.compact",
        "consensus.ask",
        "loop.set_schedule",
        "autonomy.allow",
        "code.task",
    }


# === Ollama schema conversion ===

def test_tools_to_ollama_schema_format():
    tools = [
        ToolSpec(
            name="test.tool",
            description="A test tool",
            parameters={"type": "object", "properties": {"x": {"type": "integer"}}},
            handler=lambda: None,
        ),
    ]
    schema = tools_to_ollama_schema(tools)
    assert len(schema) == 1
    assert schema[0]["type"] == "function"
    assert schema[0]["function"]["name"] == "test.tool"
    assert schema[0]["function"]["description"] == "A test tool"
    assert schema[0]["function"]["parameters"]["properties"]["x"]["type"] == "integer"


# === get_tool_by_name ===

def test_get_tool_by_name_found():
    tools = build_tools(inbox_service=MagicMock())
    t = get_tool_by_name(tools, "inbox.add")
    assert t is not None
    assert t.name == "inbox.add"


def test_get_tool_by_name_missing():
    tools = build_tools()
    t = get_tool_by_name(tools, "nonexistent.tool")
    assert t is None


# === vault.write safety ===

@pytest.mark.asyncio
async def test_vault_write_refuses_path_escape(tmp_path: Path, monkeypatch):
    """vault.write must refuse to write outside the vault root."""
    monkeypatch.setattr("backend.vault.resolve_vault_path", lambda: tmp_path)

    result = await t_mod.vault_write("../../etc/passwd", "evil")
    assert "error" in result
    assert result["error"] == "path_escape"


@pytest.mark.asyncio
async def test_vault_write_refuses_user_authored_folders(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("backend.vault.resolve_vault_path", lambda: tmp_path)

    result = await t_mod.vault_write("aa) Murun/wants.md", "injected")
    assert "error" in result
    assert result["error"] == "user_authored"


@pytest.mark.asyncio
async def test_vault_write_succeeds_to_wiki(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("backend.vault.resolve_vault_path", lambda: tmp_path)

    result = await t_mod.vault_write("wiki/test.md", "# hi")
    assert result.get("ok") is True
    assert (tmp_path / "wiki" / "test.md").exists()
    assert (tmp_path / "wiki" / "test.md").read_text() == "# hi"
