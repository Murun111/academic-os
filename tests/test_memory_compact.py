"""Tests for backend.services.memory_compact — the memory distillation pass.

All tests run OFFLINE. ``backend.vault.resolve_vault_path`` is monkeypatched to
a pytest ``tmp_path`` and ``memory_index._embed_sync`` is stubbed so no Ollama
call is made (embedding-based merge degrades to a no-op unless a test injects
vectors explicitly).

Coverage:
- parse_bullet() round-trips a _make_bullet() string.
- compaction evicts conversational noise (archived, not deleted).
- compaction supersedes duplicate subjects, keeping the newest ts.
- removed items are archived under memory/_archive/ (reversibility).
- the raw daily log under memory/log/ is never touched.
- _index.md (map-of-content) is regenerated.
- embedding similarity merges near-duplicate bodies when vectors are available.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from backend.services import memory_compact
from backend.services.memory_compact import compact_all, parse_bullet
from backend.services.memory_types import MemoryItem
from backend.services.memory_writer import _make_bullet


_MEM = "Agentic OS/memory"


@pytest.fixture(autouse=True)
def patch_vault(monkeypatch, tmp_path: Path):
    monkeypatch.setattr("backend.vault.resolve_vault_path", lambda: tmp_path)
    return tmp_path


@pytest.fixture(autouse=True)
def no_embeddings(monkeypatch):
    """Disable real Ollama embedding calls — merge degrades to subject dedup."""
    monkeypatch.setattr("backend.services.memory_index._embed_sync", lambda _t: None)


def _seed(tmp_path: Path, filename: str, bullets: list[str]) -> Path:
    p = tmp_path / _MEM / filename
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("---\nlast_updated: 2026-01-01\n---\n\n# Fact\n" + "\n".join(bullets) + "\n")
    return p


def _item(subject, body, ts, thread="t1", tags=None, kind="fact") -> MemoryItem:
    return MemoryItem(kind=kind, subject=subject, body=body, tags=tags or [],
                      source_thread=thread, ts=ts, confidence=1.0)


# ── parse_bullet ─────────────────────────────────────────────────────────────

def test_parse_bullet_roundtrips_make_bullet():
    it = _item("Net Worth", "The current net worth is -$4,764.50.",
               "2026-06-26T23:26:57Z", thread="coo-fixtest", tags=["finance", "money"])
    parsed = parse_bullet(_make_bullet(it), "fact")
    assert parsed is not None
    assert parsed.subject == "Net Worth"
    assert parsed.body == "The current net worth is -$4,764.50."
    assert parsed.source_thread == "coo-fixtest"
    assert set(parsed.tags) == {"finance", "money"}
    assert parsed.ts == "2026-06-26T23:26:57Z"


def test_parse_bullet_rejects_non_bullets():
    assert parse_bullet("# Fact", "fact") is None
    assert parse_bullet("", "fact") is None
    assert parse_bullet("just some prose", "fact") is None


# ── noise eviction ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_compaction_evicts_noise(tmp_path: Path):
    real = _item("Net Worth", "The current net worth is -$4,764.50.", "2026-06-26T10:00:00Z")
    noise = _item("Echo Response", "The assistant responded with 'done'.", "2026-06-26T11:00:00Z")
    _seed(tmp_path, "facts.md", [_make_bullet(real), _make_bullet(noise)])

    summary = await compact_all()

    facts = (tmp_path / _MEM / "facts.md").read_text()
    assert "Net Worth" in facts
    assert "Echo Response" not in facts          # evicted
    assert summary["files"]["facts.md"]["reasons"].get("noise") == 1


# ── supersede duplicate subjects ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_compaction_supersedes_duplicate_subjects_keeping_newest(tmp_path: Path):
    old = _item("COO Daily Operations", "The COO reads calendar and inbox.", "2026-06-26T10:00:00Z")
    new = _item("COO Daily Operations", "The COO owns the daily run end to end.", "2026-06-27T10:00:00Z")
    _seed(tmp_path, "facts.md", [_make_bullet(old), _make_bullet(new)])

    await compact_all()

    facts = (tmp_path / _MEM / "facts.md").read_text()
    assert "owns the daily run end to end" in facts   # newest kept
    assert "reads calendar and inbox" not in facts     # superseded


# ── reversibility: archived, not deleted ─────────────────────────────────────

@pytest.mark.asyncio
async def test_removed_items_are_archived(tmp_path: Path):
    real = _item("Net Worth", "The current net worth is -$4,764.50.", "2026-06-26T10:00:00Z")
    noise = _item("Greeting", "The assistant greeting was 'Hello'.", "2026-06-26T11:00:00Z")
    _seed(tmp_path, "facts.md", [_make_bullet(real), _make_bullet(noise)])

    await compact_all()

    archive = tmp_path / _MEM / "_archive" / "facts.md"
    assert archive.exists()
    body = archive.read_text()
    assert "Greeting" in body
    assert "_(noise)_" in body          # reason is recorded


# ── the raw log is sacred ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_compaction_never_touches_the_raw_log(tmp_path: Path):
    log = tmp_path / _MEM / "log" / "2026-06-26.md"
    log.parent.mkdir(parents=True, exist_ok=True)
    original = "---\nlast_updated: 2026-06-26\n---\n\n- [..] **Echo** — noise stays here\n"
    log.write_text(original)
    _seed(tmp_path, "facts.md", [_make_bullet(_item("X", "A durable fact body here.", "2026-06-26T10:00:00Z"))])

    await compact_all()

    assert log.read_text() == original   # untouched, byte for byte


# ── map-of-content ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_compaction_regenerates_index(tmp_path: Path):
    _seed(tmp_path, "facts.md", [_make_bullet(_item("X", "A durable fact body here.", "2026-06-26T10:00:00Z"))])

    await compact_all()

    index = tmp_path / _MEM / "_index.md"
    assert index.exists()
    assert "[[facts]]" in index.read_text()


# ── embedding-based near-duplicate merge ─────────────────────────────────────

@pytest.mark.asyncio
async def test_embedding_merge_collapses_near_duplicates(tmp_path: Path, monkeypatch):
    a = _item("Cashflow A", "The 30-day cashflow is negative.", "2026-06-26T10:00:00Z")
    b = _item("Cashflow B", "The thirty day cash flow trend is negative.", "2026-06-27T10:00:00Z")
    _seed(tmp_path, "facts.md", [_make_bullet(a), _make_bullet(b)])

    # Both bodies map to the same vector → cosine 1.0 ≥ threshold → merge.
    monkeypatch.setattr("backend.services.memory_index._embed_sync", lambda _t: [1.0, 0.0, 0.0])

    summary = await compact_all()

    assert summary["files"]["facts.md"]["reasons"].get("similar") == 1
    assert summary["files"]["facts.md"]["kept"] == 1
