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
