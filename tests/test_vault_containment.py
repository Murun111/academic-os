"""Vault containment tests — OFFLINE.

Covers the realpath + case-folded containment fence added to vault_read /
vault_write in backend/services/tools.py:

(a) '../' style path escapes are refused for both vault_read and vault_write.
(b) The data/connectors/ credential fence holds even when the caller spells
    it with different casing (data/Connectors/canvas.json) — macOS's default
    case-insensitive filesystem would otherwise let a case-variant slip past
    a naive containment check.
(c) vault_write refuses to write data/autonomy_allow.json (and the data/
    subtree generally) — app config/credentials are not agent-writable.
(d) A normal in-vault read/write still works — the fence isn't overzealous.

ACADEMIC_OS_DATA is already redirected to a tmp dir per-test by the autouse
``_isolate_data_root`` fixture in conftest.py, but these tests monkeypatch
``backend.vault.resolve_vault_path`` directly (matching test_audit_hardening.py
/ test_tools.py conventions) so each test owns an explicit, inspectable root.
"""
from __future__ import annotations

from pathlib import Path

import pytest

import backend.services.tools as tools_mod


# === (a) path escape ==========================================================

@pytest.mark.asyncio
async def test_vault_read_rejects_sibling_escape(tmp_path: Path, monkeypatch):
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    sibling = tmp_path / "sibling"
    sibling.mkdir()
    (sibling / "x").write_text("secret")
    monkeypatch.setattr("backend.vault.resolve_vault_path", lambda: vault_root)

    result = await tools_mod.vault_read("../sibling/x")

    assert result["error"] == "path_escape"


@pytest.mark.asyncio
async def test_vault_write_rejects_sibling_escape(tmp_path: Path, monkeypatch):
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    monkeypatch.setattr("backend.vault.resolve_vault_path", lambda: vault_root)

    result = await tools_mod.vault_write("../sibling/x", "injected")

    assert result["error"] == "path_escape"
    assert not (tmp_path / "sibling" / "x").exists()


# === (b) case-insensitive connectors fence ====================================

@pytest.mark.asyncio
async def test_vault_read_rejects_connectors_exact_case(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("backend.vault.resolve_vault_path", lambda: tmp_path)
    connectors = tmp_path / "data" / "connectors"
    connectors.mkdir(parents=True)
    (connectors / "canvas.json").write_text('{"token": "secret"}')

    result = await tools_mod.vault_read("data/connectors/canvas.json")

    assert result["error"] == "forbidden"


@pytest.mark.asyncio
async def test_vault_read_rejects_connectors_case_variant(tmp_path: Path, monkeypatch):
    """Same file, requested with different casing on the connectors segment.
    macOS's default case-insensitive filesystem resolves this to the same
    file on disk, so the fence must hold here too, not just on exact case."""
    monkeypatch.setattr("backend.vault.resolve_vault_path", lambda: tmp_path)
    connectors = tmp_path / "data" / "connectors"
    connectors.mkdir(parents=True)
    (connectors / "canvas.json").write_text('{"token": "secret"}')

    result = await tools_mod.vault_read("data/Connectors/canvas.json")

    assert result["error"] == "forbidden"


# === (c) vault_write refuses data/autonomy_allow.json =========================

@pytest.mark.asyncio
async def test_vault_write_refuses_autonomy_allow_file(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("backend.vault.resolve_vault_path", lambda: tmp_path)
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    original = '{"allowed": []}'
    (data_dir / "autonomy_allow.json").write_text(original)

    result = await tools_mod.vault_write("data/autonomy_allow.json", '{"allowed": ["evil"]}')

    assert result["error"] == "forbidden"
    assert (data_dir / "autonomy_allow.json").read_text() == original


@pytest.mark.asyncio
async def test_vault_write_refuses_autonomy_allow_case_variant(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("backend.vault.resolve_vault_path", lambda: tmp_path)

    result = await tools_mod.vault_write("Data/autonomy_allow.json", '{"allowed": ["evil"]}')

    assert result["error"] == "forbidden"
    assert not (tmp_path / "data" / "autonomy_allow.json").exists()
    assert not (tmp_path / "Data" / "autonomy_allow.json").exists()


# === (d) normal in-vault read/write still works ================================

@pytest.mark.asyncio
async def test_vault_write_then_read_roundtrip_in_notes(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("backend.vault.resolve_vault_path", lambda: tmp_path)

    write_result = await tools_mod.vault_write("notes/plan.md", "# Plan\n\nStep one.")
    assert write_result.get("ok") is True

    read_result = await tools_mod.vault_read("notes/plan.md")
    assert "error" not in read_result
    assert read_result["content"] == "# Plan\n\nStep one."
