"""Tests for restore-from-backup: preview_restore, run_restore, snapshot
retention, and the /api/system/restore* router endpoints."""
import json
from datetime import datetime as _real_datetime, timedelta
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.services import backup
from backend.routers.system import router as system_router


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("ACADEMIC_OS_DATA", str(tmp_path / "root"))
    (tmp_path / "root" / "data").mkdir(parents=True)
    (tmp_path / "root" / "data" / "profile.json").write_text('{"stage": "highschool"}')
    (tmp_path / "root" / "notes").mkdir()
    (tmp_path / "root" / "notes" / "a.md").write_text("hello")
    return tmp_path


class _StepClock:
    """Deterministic stand-in for the `datetime` name in backup.py: each
    `.now()` call advances by 1s, so back-to-back run_restore() calls in a
    test get distinct pre-restore-snapshots/<ts> directory names (the real
    clock's second-resolution strftime format can collide within a test)."""

    def __init__(self):
        self._t = _real_datetime(2024, 1, 1)

    def now(self):
        self._t += timedelta(seconds=1)
        return self._t


@pytest.fixture
def step_clock(monkeypatch):
    clock = _StepClock()
    monkeypatch.setattr(backup, "datetime", clock)
    return clock


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("ACADEMIC_OS_DATA", str(tmp_path / "root"))
    (tmp_path / "root" / "data").mkdir(parents=True)
    (tmp_path / "root" / "data" / "profile.json").write_text('{"stage": "highschool"}')
    (tmp_path / "root" / "notes").mkdir()
    (tmp_path / "root" / "notes" / "a.md").write_text("hello")
    app = FastAPI()
    app.include_router(system_router)
    with TestClient(app) as c:
        yield c


def test_preview_restore_no_backup(env):
    result = backup.preview_restore()
    assert result["ok"] is False
    assert result["error"] == "no_backup_found"
    assert result["backup_dir"] is None
    assert result["counts"] == {"add": 0, "overwrite": 0, "delete": 0}


def test_restore_roundtrip(env, tmp_path):
    dest = tmp_path / "clouddrive"
    backup.set_path(str(dest))
    backup.run_backup()
    # run_backup writes cfg["last_backup"] to data/backup.json *after* mirroring
    # data/, so the live and backed-up copies of that one file always diverge
    # right away. It's baseline noise from every run_backup call, not
    # something this test mutates — accounted for in the counts below.

    root = tmp_path / "root"
    (root / "notes" / "a.md").write_text("hello world, this content was modified live")  # overwrite
    (root / "notes" / "b.md").write_text("extra file only on live, not in backup")  # delete
    (root / "data" / "profile.json").unlink()  # add back

    preview = backup.preview_restore()
    assert preview["ok"] is True
    assert preview["counts"] == {"add": 1, "overwrite": 2, "delete": 1}
    assert preview["add"] == ["data/profile.json"]
    assert preview["overwrite"] == ["data/backup.json", "notes/a.md"]
    assert preview["delete"] == ["notes/b.md"]

    result = backup.run_restore()
    assert result["ok"] is True
    assert result["restored"] == 3
    assert result["deleted"] == 1

    assert json.loads((root / "data" / "profile.json").read_text())["stage"] == "highschool"
    assert (root / "notes" / "a.md").read_text() == "hello"
    assert not (root / "notes" / "b.md").exists()

    # live now matches the backup exactly
    after = backup.preview_restore()
    assert after["counts"] == {"add": 0, "overwrite": 0, "delete": 0}


def test_restore_creates_pre_restore_snapshot(env, tmp_path):
    dest = tmp_path / "clouddrive"
    backup.set_path(str(dest))
    backup.run_backup()

    root = tmp_path / "root"
    (root / "notes" / "a.md").write_text("mutated live content before restore")
    (root / "notes" / "b.md").write_text("extra live-only file")
    (root / "data" / "profile.json").unlink()

    result = backup.run_restore()
    assert result["snapshot"] is not None
    snap_dir = Path(result["snapshot"])

    assert snap_dir.parent == root / "pre-restore-snapshots"
    assert snap_dir.is_dir()
    # snapshot captures live state as it was right before the restore ran
    assert (snap_dir / "notes" / "a.md").read_text() == "mutated live content before restore"
    assert (snap_dir / "notes" / "b.md").read_text() == "extra live-only file"
    assert not (snap_dir / "data" / "profile.json").exists()


def test_snapshot_retention_keeps_three(env, tmp_path, step_clock):
    dest = tmp_path / "clouddrive"
    backup.set_path(str(dest))
    backup.run_backup()

    root = tmp_path / "root"
    for _ in range(4):
        result = backup.run_restore()
        assert result["ok"] is True

    snap_root = root / "pre-restore-snapshots"
    snapshot_dirs = [p for p in snap_root.iterdir() if p.is_dir()]
    assert len(snapshot_dirs) == 3


def test_router_restore_preview_no_backup(client):
    r = client.get("/api/system/restore/preview")
    assert r.status_code == 200
    assert r.json() == backup.preview_restore()


def test_router_restore_preview_and_run(client, tmp_path):
    root = tmp_path / "root"
    dest = tmp_path / "clouddrive"
    backup.set_path(str(dest))
    backup.run_backup()

    (root / "notes" / "a.md").write_text("modified through the router test")

    preview = client.get("/api/system/restore/preview")
    assert preview.status_code == 200
    preview_body = preview.json()
    assert preview_body["ok"] is True
    # data/backup.json also shows as an overwrite: run_backup() stamps its
    # last_backup timestamp into that file *after* mirroring data/, so it
    # diverges from the backed-up copy on every run_backup call.
    assert preview_body["counts"] == {"add": 0, "overwrite": 2, "delete": 0}

    run = client.post("/api/system/restore")
    assert run.status_code == 200
    run_body = run.json()
    assert run_body["ok"] is True
    assert run_body["restored"] == 2
    assert run_body["deleted"] == 0
    assert run_body["snapshot"] is not None

    assert (root / "notes" / "a.md").read_text() == "hello"
