"""Tests for backend.services.code_task — OFFLINE (no real CLI is spawned).

Strategy:
  - monkeypatch PROJECTS_ROOT to a tmp_path so nothing touches ~/Code.
  - monkeypatch asyncio.create_task to a no-op so _build() never actually
    runs subprocess (we close the coroutine to silence "never awaited" warnings).
  - Verify: dir creation, return shape, _slug sanitisation, backend default.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import backend.services.code_task as ct


# ── Helpers ────────────────────────────────────────────────────────────────────

def _noop_create_task(coro):
    """Accept the coroutine, close it (to prevent 'never awaited' warnings), return mock."""
    try:
        coro.close()
    except Exception:
        pass
    return MagicMock()


# ── _slug ─────────────────────────────────────────────────────────────────────

def test_slug_spaces_become_underscores():
    assert ct._slug("my cool project") == "my_cool_project"


def test_slug_slashes_become_underscores():
    assert ct._slug("foo/bar/baz") == "foo_bar_baz"


def test_slug_special_chars_become_underscores():
    assert ct._slug("hello world! v2.0") == "hello_world__v2_0"


def test_slug_already_clean_unchanged():
    assert ct._slug("my-project_2") == "my-project_2"


def test_slug_empty_fallback():
    assert ct._slug("") == "project"


def test_slug_only_special_chars_fallback():
    assert ct._slug("!!!") == "project"


# ── run_code_task — immediate return ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_run_code_task_returns_building(tmp_path, monkeypatch):
    """run_code_task must return {ok:True, status:'building'} immediately."""
    monkeypatch.setattr(ct, "PROJECTS_ROOT", tmp_path / "projects")
    monkeypatch.setattr(asyncio, "create_task", _noop_create_task)

    result = await ct.run_code_task("build a hello world app", "hello-world")

    assert result["ok"] is True
    assert result["status"] == "building"
    assert result["project"] == "hello-world"
    assert result["pipeline"] == "claude"
    assert "dir" in result
    assert "note" in result


@pytest.mark.asyncio
async def test_run_code_task_creates_project_dir(tmp_path, monkeypatch):
    """Project directory must be created before the function returns."""
    monkeypatch.setattr(ct, "PROJECTS_ROOT", tmp_path / "projects")
    monkeypatch.setattr(asyncio, "create_task", _noop_create_task)

    await ct.run_code_task("build something", "my-app")

    expected = tmp_path / "projects" / "my-app"
    assert expected.is_dir()


@pytest.mark.asyncio
async def test_run_code_task_dir_in_result_matches_created_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(ct, "PROJECTS_ROOT", tmp_path / "projects")
    monkeypatch.setattr(asyncio, "create_task", _noop_create_task)

    result = await ct.run_code_task("build something", "my-app")

    assert result["dir"] == str(tmp_path / "projects" / "my-app")


# ── backend selection ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_unknown_backend_defaults_to_claude(tmp_path, monkeypatch):
    """Any unrecognised backend name must silently default to 'claude'."""
    monkeypatch.setattr(ct, "PROJECTS_ROOT", tmp_path / "projects")
    monkeypatch.setattr(asyncio, "create_task", _noop_create_task)

    result = await ct.run_code_task("build x", "proj", backend="gpt-99")

    assert result["ok"] is True
    assert result["pipeline"] == "claude"


@pytest.mark.asyncio
async def test_codex_backend_accepted(tmp_path, monkeypatch):
    monkeypatch.setattr(ct, "PROJECTS_ROOT", tmp_path / "projects")
    monkeypatch.setattr(asyncio, "create_task", _noop_create_task)

    result = await ct.run_code_task("build y", "proj2", backend="codex")

    assert result["ok"] is True
    assert result["pipeline"] == "codex"


@pytest.mark.asyncio
async def test_claude_backend_accepted(tmp_path, monkeypatch):
    monkeypatch.setattr(ct, "PROJECTS_ROOT", tmp_path / "projects")
    monkeypatch.setattr(asyncio, "create_task", _noop_create_task)

    result = await ct.run_code_task("build z", "proj3", backend="claude")

    assert result["ok"] is True
    assert result["pipeline"] == "claude"


# ── slug applied to project name ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_spaces_in_project_name_are_slugified(tmp_path, monkeypatch):
    """Spaces in the project name must be slugified for the dir and result."""
    monkeypatch.setattr(ct, "PROJECTS_ROOT", tmp_path / "projects")
    monkeypatch.setattr(asyncio, "create_task", _noop_create_task)

    result = await ct.run_code_task("build it", "my cool app")

    expected_dir = tmp_path / "projects" / "my_cool_app"
    assert expected_dir.is_dir()
    assert result["dir"] == str(expected_dir)
