"""Tests for backend.services.reminders — OFFLINE (monkeypatched subprocess).

All I/O is monkeypatched; no real osascript or Reminders.app is called.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

import backend.services.reminders as rem_mod


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_proc(
    returncode: int = 0,
    stdout: str = "reminder-id-123",
    stderr: str = "",
) -> MagicMock:
    proc = MagicMock()
    proc.returncode = returncode
    proc.stdout = stdout
    proc.stderr = stderr
    return proc


# ── Platform guard ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_non_darwin_returns_error_without_calling_subprocess(monkeypatch):
    """Non-macOS must return ok:False immediately; subprocess.run must NOT be called."""
    monkeypatch.setattr(rem_mod.sys, "platform", "win32")
    spy = MagicMock()
    monkeypatch.setattr(rem_mod.subprocess, "run", spy)
    result = await rem_mod.create_reminder("Buy milk")
    assert result == {"ok": False, "error": "reminders only on macOS"}
    spy.assert_not_called()


@pytest.mark.asyncio
async def test_linux_returns_error_without_calling_subprocess(monkeypatch):
    monkeypatch.setattr(rem_mod.sys, "platform", "linux")
    spy = MagicMock()
    monkeypatch.setattr(rem_mod.subprocess, "run", spy)
    result = await rem_mod.create_reminder("Task")
    assert result["ok"] is False
    spy.assert_not_called()


# ── Happy-path ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_basic_title_returns_ok_and_id(monkeypatch):
    monkeypatch.setattr(rem_mod.sys, "platform", "darwin")
    monkeypatch.setattr(rem_mod.subprocess, "run", lambda *a, **kw: _make_proc())
    result = await rem_mod.create_reminder("Buy milk")
    assert result["ok"] is True
    assert result["id"] == "reminder-id-123"


@pytest.mark.asyncio
async def test_script_contains_title(monkeypatch):
    monkeypatch.setattr(rem_mod.sys, "platform", "darwin")
    captured: list[str] = []

    def fake_run(cmd, **kw):
        captured.append(cmd[2])  # ["osascript", "-e", <script>]
        return _make_proc()

    monkeypatch.setattr(rem_mod.subprocess, "run", fake_run)
    await rem_mod.create_reminder("Doctor appointment")
    assert len(captured) == 1
    assert "Doctor appointment" in captured[0]


# ── Due-date block ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_valid_due_date_year_month_day_in_script(monkeypatch):
    """A valid YYYY-MM-DD due date must produce locale-independent AppleScript."""
    monkeypatch.setattr(rem_mod.sys, "platform", "darwin")
    captured: list[str] = []

    def fake_run(cmd, **kw):
        captured.append(cmd[2])
        return _make_proc()

    monkeypatch.setattr(rem_mod.subprocess, "run", fake_run)
    await rem_mod.create_reminder("Doctor appt", due="2026-08-12")
    script = captured[0]
    assert "set year of dueDate to 2026" in script
    assert "set month of dueDate to 8" in script
    assert "set day of dueDate to 12" in script
    assert "due date:dueDate" in script


@pytest.mark.asyncio
async def test_invalid_due_date_skipped(monkeypatch):
    """Malformed due date must be silently skipped — no dueDate variable in script."""
    monkeypatch.setattr(rem_mod.sys, "platform", "darwin")
    captured: list[str] = []

    def fake_run(cmd, **kw):
        captured.append(cmd[2])
        return _make_proc()

    monkeypatch.setattr(rem_mod.subprocess, "run", fake_run)
    await rem_mod.create_reminder("Bad due", due="not-a-date")
    assert "dueDate" not in captured[0]


@pytest.mark.asyncio
async def test_no_due_date_no_duedate_block(monkeypatch):
    monkeypatch.setattr(rem_mod.sys, "platform", "darwin")
    captured: list[str] = []

    def fake_run(cmd, **kw):
        captured.append(cmd[2])
        return _make_proc()

    monkeypatch.setattr(rem_mod.subprocess, "run", fake_run)
    await rem_mod.create_reminder("Simple task")
    assert "dueDate" not in captured[0]


# ── Escape ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_title_double_quote_is_escaped(monkeypatch):
    """A double-quote in the title must be backslash-escaped in the AppleScript."""
    monkeypatch.setattr(rem_mod.sys, "platform", "darwin")
    captured: list[str] = []

    def fake_run(cmd, **kw):
        captured.append(cmd[2])
        return _make_proc()

    monkeypatch.setattr(rem_mod.subprocess, "run", fake_run)
    await rem_mod.create_reminder('Read "Dune"')
    assert r'Read \"Dune\"' in captured[0]


@pytest.mark.asyncio
async def test_notes_double_quote_is_escaped(monkeypatch):
    monkeypatch.setattr(rem_mod.sys, "platform", "darwin")
    captured: list[str] = []

    def fake_run(cmd, **kw):
        captured.append(cmd[2])
        return _make_proc()

    monkeypatch.setattr(rem_mod.subprocess, "run", fake_run)
    await rem_mod.create_reminder("Task", notes='See "section 3"')
    assert r'See \"section 3\"' in captured[0]


# ── Error paths ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_non_zero_returncode_returns_error(monkeypatch):
    monkeypatch.setattr(rem_mod.sys, "platform", "darwin")
    monkeypatch.setattr(
        rem_mod.subprocess, "run",
        lambda *a, **kw: _make_proc(
            returncode=1,
            stderr="Not authorized to send Apple events to Reminders",
        ),
    )
    result = await rem_mod.create_reminder("Test")
    assert result["ok"] is False
    assert "Not authorized" in result["error"]


@pytest.mark.asyncio
async def test_subprocess_exception_returns_error_not_raise(monkeypatch):
    monkeypatch.setattr(rem_mod.sys, "platform", "darwin")

    def boom(*a, **kw):
        raise TimeoutError("timed out after 12s")

    monkeypatch.setattr(rem_mod.subprocess, "run", boom)
    result = await rem_mod.create_reminder("Test")
    assert result["ok"] is False
    assert "timed out" in result["error"]


@pytest.mark.asyncio
async def test_error_message_capped_at_200_chars(monkeypatch):
    monkeypatch.setattr(rem_mod.sys, "platform", "darwin")
    long_stderr = "E" * 500
    monkeypatch.setattr(
        rem_mod.subprocess, "run",
        lambda *a, **kw: _make_proc(returncode=1, stderr=long_stderr),
    )
    result = await rem_mod.create_reminder("Test")
    assert result["ok"] is False
    assert len(result["error"]) <= 200
