"""Tests for backend.vault (Academic OS data-root resolution)."""
from pathlib import Path

from backend.vault import _FALLBACK, resolve_vault_path, agentic_os_dir, AGENTIC_OS_DIR


def test_resolve_from_env(monkeypatch, tmp_path):
    """When ACADEMIC_OS_DATA is set, use it (creating it if needed)."""
    target = tmp_path / "custom-data"
    monkeypatch.setenv("ACADEMIC_OS_DATA", str(target))
    p = resolve_vault_path()
    assert p == target
    assert p.exists()


def test_fallback_is_home_dot_dir(monkeypatch):
    """When env is unset, fall back to ~/.academic-os."""
    monkeypatch.delenv("ACADEMIC_OS_DATA", raising=False)
    assert _FALLBACK == Path.home() / ".academic-os"


def test_resolve_creates_missing_dir(monkeypatch, tmp_path):
    """A nonexistent data root is created, not an error."""
    target = tmp_path / "does-not-exist-yet"
    monkeypatch.setenv("ACADEMIC_OS_DATA", str(target))
    assert not target.exists()
    p = resolve_vault_path()
    assert p == target and target.is_dir()


def test_agentic_os_dir_is_data_root(monkeypatch, tmp_path):
    """agentic_os_dir() (compat name) returns the data root itself — callers
    append their own subpaths like data/inbox."""
    monkeypatch.setenv("ACADEMIC_OS_DATA", str(tmp_path))
    assert agentic_os_dir() == tmp_path


def test_live_re_resolution(monkeypatch, tmp_path):
    """agentic_os_dir() re-resolves per call; the import-time constant is
    whatever the env was at import."""
    a, b = tmp_path / "a", tmp_path / "b"
    monkeypatch.setenv("ACADEMIC_OS_DATA", str(a))
    assert agentic_os_dir() == a
    monkeypatch.setenv("ACADEMIC_OS_DATA", str(b))
    assert agentic_os_dir() == b
    assert isinstance(AGENTIC_OS_DIR, Path)
