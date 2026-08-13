"""Audit-hardening regression tests — OFFLINE.

Covers five hardening surfaces exercised during a security/data-safety audit:

1. vault_read: path-escape and data/connectors/ reads are refused; normal
   notes files still read fine.
2. autonomy allowlist: resolves under the data root (data/autonomy_allow.json)
   and the legacy fork-era file gets migrated in on first use.
3. run_backup excludes data/connectors/ (LMS credentials); run_restore never
   deletes or copies connectors files.
4. Atomic config writes: a mid-save os.replace failure in backup.set_path
   leaves the original file on disk intact and valid.
5. /ws/events refuses a hostile browser Origin and accepts no-Origin
   connections (non-browser clients, tests).

All vault/data-root I/O is redirected to tmp dirs — either via the autouse
``_isolate_data_root`` fixture in conftest.py (ACADEMIC_OS_DATA env var) or by
monkeypatching ``backend.vault.resolve_vault_path`` directly, matching the
existing test suite's conventions (see test_tools.py, test_agent_admin.py).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

import backend.services.agent_admin as admin_mod
import backend.services.backup as backup_mod
import backend.services.tools as tools_mod
from backend.app import app


# === 1. vault_read hardening ================================================

@pytest.mark.asyncio
async def test_vault_read_rejects_path_escape(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("backend.vault.resolve_vault_path", lambda: tmp_path)

    result = await tools_mod.vault_read("../../etc/passwd")

    assert result["error"] == "path_escape"


@pytest.mark.asyncio
async def test_vault_read_rejects_connectors_dir(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("backend.vault.resolve_vault_path", lambda: tmp_path)
    connectors = tmp_path / "data" / "connectors"
    connectors.mkdir(parents=True)
    (connectors / "canvas_token.json").write_text('{"token": "secret"}')

    result = await tools_mod.vault_read("data/connectors/canvas_token.json")

    assert result["error"] == "forbidden"


@pytest.mark.asyncio
async def test_vault_read_normal_notes_file_still_works(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("backend.vault.resolve_vault_path", lambda: tmp_path)
    notes_dir = tmp_path / "notes"
    notes_dir.mkdir()
    (notes_dir / "hello.md").write_text("# Hello")

    result = await tools_mod.vault_read("notes/hello.md")

    assert "error" not in result
    assert result["content"] == "# Hello"


# === 2. autonomy allowlist location + migration =============================

def test_allow_file_resolves_under_data_root(tmp_path: Path, monkeypatch):
    data_root = tmp_path / "data-root"
    monkeypatch.setattr("backend.vault.resolve_vault_path", lambda: data_root)
    monkeypatch.setattr(admin_mod, "_LEGACY_ALLOW_FILE", tmp_path / "no-legacy-file")

    resolved = admin_mod._allow_file()

    assert resolved == data_root / "data" / "autonomy_allow.json"


def test_allow_file_migrates_old_format_file(tmp_path: Path, monkeypatch):
    """A pre-existing fork-era file at the legacy location gets copied into
    the app data root the first time _allow_file() resolves, and the legacy
    file is left in place (never deleted)."""
    data_root = tmp_path / "data-root"
    legacy = tmp_path / "old-home" / ".agentic-os" / "autonomy_allow.json"
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text(json.dumps(["legacy.tool.one", "legacy.tool.two"]))

    monkeypatch.setattr("backend.vault.resolve_vault_path", lambda: data_root)
    monkeypatch.setattr(admin_mod, "_LEGACY_ALLOW_FILE", legacy)

    resolved = admin_mod._allow_file()

    assert resolved == data_root / "data" / "autonomy_allow.json"
    assert resolved.exists()
    assert json.loads(resolved.read_text()) == ["legacy.tool.one", "legacy.tool.two"]
    assert legacy.exists()  # migration copies, never moves/deletes


# === 3. backup/restore exclude data/connectors/ ==============================

def test_run_backup_excludes_connectors_dir(tmp_path: Path, monkeypatch):
    data_root = tmp_path / "data-root"
    monkeypatch.setattr("backend.vault.agentic_os_dir", lambda: data_root)

    connectors = data_root / "data" / "connectors"
    connectors.mkdir(parents=True)
    (connectors / "canvas_token.json").write_text('{"token": "top-secret"}')
    (data_root / "data" / "keep.json").write_text('{"a": 1}')

    dest = tmp_path / "dest"
    backup_mod.set_path(str(dest))
    result = backup_mod.run_backup()

    assert result.get("ok") is True
    mirrored = dest / "AcademicOS-Backup" / "data"
    assert not (mirrored / "connectors").exists()
    assert (mirrored / "keep.json").exists()


def test_run_restore_never_deletes_or_copies_connectors(tmp_path: Path, monkeypatch):
    data_root = tmp_path / "data-root"
    monkeypatch.setattr("backend.vault.agentic_os_dir", lambda: data_root)

    connectors = data_root / "data" / "connectors"
    connectors.mkdir(parents=True)
    token_path = connectors / "canvas_token.json"
    token_path.write_text('{"token": "top-secret"}')
    (data_root / "data" / "keep.json").write_text('{"a": 1}')

    dest = tmp_path / "dest"
    backup_mod.set_path(str(dest))
    backup_mod.run_backup()  # connectors never enters the mirror

    # A restore diffs backup vs live and can delete live files absent from
    # the backup. Because connectors is excluded from _mirrored_files on
    # both sides, it must never show up as a delete candidate.
    result = backup_mod.run_restore()

    assert result.get("ok") is True
    assert token_path.exists()
    assert token_path.read_text() == '{"token": "top-secret"}'
    # never copied into the backup mirror either
    assert not (dest / "AcademicOS-Backup" / "data" / "connectors").exists()


# === 4. atomic writes survive a mid-save crash ===============================

def test_set_path_survives_os_replace_failure(tmp_path: Path, monkeypatch):
    data_root = tmp_path / "data-root"
    monkeypatch.setattr("backend.vault.agentic_os_dir", lambda: data_root)

    # Establish a valid original config on disk first.
    backup_mod.set_path(str(tmp_path / "backup-one"))
    config_path = backup_mod._config_path()
    original_bytes = config_path.read_bytes()
    assert json.loads(original_bytes)  # sanity: valid JSON to start

    def boom(*_args, **_kwargs):
        raise OSError("disk full mid-save")

    monkeypatch.setattr(backup_mod.os, "replace", boom)

    with pytest.raises(OSError):
        backup_mod.set_path(str(tmp_path / "backup-two"))

    # Original file untouched and still valid JSON — os.replace never
    # happened, so the tmp file (if any) never became the real file.
    assert config_path.read_bytes() == original_bytes
    assert json.loads(config_path.read_text())["path"] == str(tmp_path / "backup-one")


# === 5. /ws/events Origin check ==============================================

def test_ws_events_refuses_hostile_origin():
    client = TestClient(app)

    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(
            "/ws/events", headers={"Origin": "http://evil.example"}
        ) as ws:
            ws.receive_json()


def test_ws_events_allows_missing_origin():
    client = TestClient(app)

    with client.websocket_connect("/ws/events") as ws:
        msg = ws.receive_json()

    assert msg["type"] == "hello"
