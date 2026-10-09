"""Tests for the folder backup service."""
import json

import pytest

from backend.services import backup


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("ACADEMIC_OS_DATA", str(tmp_path / "root"))
    (tmp_path / "root" / "data").mkdir(parents=True)
    (tmp_path / "root" / "data" / "profile.json").write_text('{"stage": "highschool"}')
    (tmp_path / "root" / "notes").mkdir()
    (tmp_path / "root" / "notes" / "a.md").write_text("hello")
    return tmp_path


def test_status_empty(env):
    assert backup.status() == {"path": "", "last_backup": None}


def test_set_path_and_run(env, tmp_path):
    dest = tmp_path / "clouddrive"
    r = backup.set_path(str(dest))
    assert r["path"] == str(dest)
    result = backup.run_backup()
    assert result["ok"] is True
    mirrored = dest / "AcademicOS-Backup"
    assert json.loads((mirrored / "data" / "profile.json").read_text())["stage"] == "highschool"
    assert (mirrored / "notes" / "a.md").read_text() == "hello"
    assert backup.status()["last_backup"] is not None


def test_run_without_path_errors(env):
    assert "error" in backup.run_backup()


def test_clear_path(env, tmp_path):
    backup.set_path(str(tmp_path / "x"))
    r = backup.set_path("")
    assert r["path"] == ""


# ── F93 / F62 / F94 regressions ──────────────────────────────────────

def test_backup_prunes_deleted_files_from_mirror(env, tmp_path):
    """F93: forgotten/deleted files must not linger in the mirror."""
    (tmp_path / "root" / "notes" / "memory").mkdir()
    (tmp_path / "root" / "notes" / "memory" / "facts.md").write_text("private")
    dest = tmp_path / "cloud"
    backup.set_path(str(dest))
    assert backup.run_backup()["ok"]
    m = dest / "AcademicOS-Backup"
    assert (m / "notes" / "memory" / "facts.md").exists()
    (tmp_path / "root" / "notes" / "memory" / "facts.md").unlink()
    (tmp_path / "root" / "notes" / "memory").rmdir()
    assert backup.run_backup()["ok"]
    assert not (m / "notes" / "memory" / "facts.md").exists()
    assert not (m / "notes" / "memory").exists()
    assert (m / "notes" / "a.md").read_text() == "hello"


def test_backup_prune_never_touches_connectors_in_mirror(env, tmp_path):
    dest = tmp_path / "cloud"
    backup.set_path(str(dest))
    backup.run_backup()
    keep = dest / "AcademicOS-Backup" / "data" / "connectors"
    keep.mkdir(parents=True)
    (keep / "x.json").write_text("{}")
    backup.run_backup()
    assert (keep / "x.json").exists()  # outside the mirrored scope


def test_set_path_rejects_relative_and_inside_data_root(env, tmp_path):
    r = backup.set_path("Backups")
    assert "error" in r and "absolute" in r["error"]
    assert not (__import__("pathlib").Path.cwd() / "Backups").exists()
    r = backup.set_path(str(tmp_path / "root" / "data" / "bk"))
    assert "error" in r and "data folder" in r["error"]
    assert not (tmp_path / "root" / "data" / "bk").exists()
    assert backup.status()["path"] == ""


def test_restore_snapshot_excludes_credentials(env, tmp_path):
    """F94: pre-restore snapshot must not copy data/connectors."""
    conn = tmp_path / "root" / "data" / "connectors"
    conn.mkdir()
    (conn / "canvas.json").write_text('{"token": "SECRET"}')
    dest = tmp_path / "cloud"
    backup.set_path(str(dest))
    backup.run_backup()
    r = backup.run_restore()
    assert r["ok"], r
    snap = __import__("pathlib").Path(r["snapshot"])
    assert not (snap / "data" / "connectors").exists()
    assert (snap / "data" / "profile.json").exists()
    assert (conn / "canvas.json").exists()  # live credentials untouched


def test_old_snapshots_are_scrubbed_of_connectors(env, tmp_path):
    snap_root = tmp_path / "root" / "pre-restore-snapshots"
    old = snap_root / "20200101-000000" / "data" / "connectors"
    old.mkdir(parents=True)
    (old / "canvas.json").write_text("SECRET")
    backup._prune_snapshots(snap_root)
    assert not old.exists()
