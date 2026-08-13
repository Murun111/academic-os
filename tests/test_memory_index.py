"""Tests for backend.services.memory_index — Phase 1.1 Module A.

All tests run **offline** — Ollama is never contacted.  _embed_sync is
monkeypatched for deterministic behaviour.  DB_PATH is redirected to a
temporary file so tests never pollute the real index.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from backend.services.memory_types import MemoryItem


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_item(
    subject: str = "test subject",
    body: str = "test body",
    kind: str = "fact",
) -> MemoryItem:
    return MemoryItem(kind=kind, subject=subject, body=body)


def _unit_vec(n: int, hot: int) -> list[float]:
    """One-hot unit vector of length *n* at position *hot*."""
    v = [0.0] * n
    v[hot % n] = 1.0
    return v


def _fake_embed(text: str) -> list[float] | None:
    """Deterministic fake: 8-D unit vector derived from the text's char-sum."""
    n = 8
    seed = sum(ord(c) for c in text) % n
    return _unit_vec(n, seed)


def _patch_embed(monkeypatch, fn=_fake_embed):
    import backend.services.memory_index as idx
    monkeypatch.setattr(idx, "_embed_sync", fn)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def tmp_db(tmp_path: Path, monkeypatch):
    """Redirect DB_PATH + reset lazy-init flag for every test."""
    import backend.services.memory_index as idx

    new_path = tmp_path / "memory" / "test_index.db"
    monkeypatch.setattr(idx, "DB_PATH", new_path)
    monkeypatch.setattr(idx, "_db_initialized", False)
    yield new_path


# ---------------------------------------------------------------------------
# init_db
# ---------------------------------------------------------------------------

def test_init_creates_db_file(tmp_db):
    import backend.services.memory_index as idx
    idx.init_db()
    assert tmp_db.exists()


def test_init_is_idempotent(tmp_db):
    import backend.services.memory_index as idx
    idx.init_db()
    idx.init_db()  # must not raise
    assert tmp_db.exists()


# ---------------------------------------------------------------------------
# upsert_item + all_items — roundtrip
# ---------------------------------------------------------------------------

def test_upsert_returns_sha1_hex(monkeypatch):
    _patch_embed(monkeypatch)
    import backend.services.memory_index as idx

    item_id = idx.upsert_item(_make_item("Architecture", "SQLite + Ollama."))
    assert len(item_id) == 40
    assert all(c in "0123456789abcdef" for c in item_id)


def test_upsert_sets_item_id_on_object(monkeypatch):
    _patch_embed(monkeypatch)
    import backend.services.memory_index as idx

    item = _make_item("Architecture", "SQLite + Ollama.")
    returned_id = idx.upsert_item(item)
    assert item.item_id == returned_id


def test_all_items_roundtrip(monkeypatch):
    _patch_embed(monkeypatch)
    import backend.services.memory_index as idx

    item = _make_item("Agentic OS architecture", "Uses SQLite and Ollama.")
    item_id = idx.upsert_item(item)

    items = idx.all_items()
    assert len(items) == 1
    assert items[0].subject == "Agentic OS architecture"
    assert items[0].item_id == item_id


def test_all_items_multiple(monkeypatch):
    _patch_embed(monkeypatch)
    import backend.services.memory_index as idx

    for i in range(5):
        idx.upsert_item(_make_item(f"subject {i}", f"body {i}"))
    assert len(idx.all_items()) == 5


def test_upsert_is_idempotent(monkeypatch):
    """Same item twice → single row, same id."""
    _patch_embed(monkeypatch)
    import backend.services.memory_index as idx

    item = _make_item("idempotent subject", "idempotent body")
    id1 = idx.upsert_item(item)
    id2 = idx.upsert_item(item)
    assert id1 == id2
    assert len(idx.all_items()) == 1


def test_all_items_empty_db():
    import backend.services.memory_index as idx
    assert idx.all_items() == []


# ---------------------------------------------------------------------------
# find_similar — embedding path
# ---------------------------------------------------------------------------

def test_find_similar_matches_identical_item(monkeypatch):
    """Identical text → same embedding → cosine 1.0 ≥ 0.92 → match."""
    _patch_embed(monkeypatch)
    import backend.services.memory_index as idx

    stored = _make_item("Python tips", "Use list comprehensions.")
    idx.upsert_item(stored)

    candidate = _make_item("Python tips", "Use list comprehensions.")
    result = idx.find_similar(candidate, threshold=0.92)
    assert result is not None
    assert result.subject == "Python tips"


def test_find_similar_orthogonal_embeddings_no_match(monkeypatch):
    """Orthogonal embeddings → cosine 0.0 < 0.92 → no match."""
    import backend.services.memory_index as idx

    # Stored item gets vec[0], candidate uses vec[1] set directly.
    call_count = [0]

    def sequential(text: str) -> list[float] | None:
        v = _unit_vec(8, call_count[0] % 2)
        call_count[0] += 1
        return v

    monkeypatch.setattr(idx, "_embed_sync", sequential)

    stored = _make_item("topic A", "content A")
    idx.upsert_item(stored)  # gets _unit_vec(8, 0)

    candidate = _make_item("topic B", "content B")
    candidate.embedding = _unit_vec(8, 1)   # pre-set so find_similar uses it
    result = idx.find_similar(candidate, threshold=0.92)
    assert result is None


def test_find_similar_below_custom_threshold(monkeypatch):
    """Cosine 1.0 still beats a threshold of 0.5 — sanity check."""
    _patch_embed(monkeypatch)
    import backend.services.memory_index as idx

    idx.upsert_item(_make_item("topic", "body"))
    candidate = _make_item("topic", "body")
    assert idx.find_similar(candidate, threshold=0.5) is not None


# ---------------------------------------------------------------------------
# find_similar — text-fallback path (embed returns None)
# ---------------------------------------------------------------------------

def test_find_similar_text_fallback_exact_match(monkeypatch):
    import backend.services.memory_index as idx

    monkeypatch.setattr(idx, "_embed_sync", lambda _: None)
    stored = _make_item("fallback subject", "fallback body")
    idx.upsert_item(stored)

    candidate = _make_item("fallback subject", "fallback body")
    result = idx.find_similar(candidate, threshold=0.92)
    assert result is not None
    assert result.subject == "fallback subject"


def test_find_similar_text_fallback_no_match_different_body(monkeypatch):
    import backend.services.memory_index as idx

    monkeypatch.setattr(idx, "_embed_sync", lambda _: None)
    idx.upsert_item(_make_item("subject X", "original body"))

    candidate = _make_item("subject X", "different body")
    result = idx.find_similar(candidate, threshold=0.92)
    assert result is None


def test_find_similar_text_fallback_no_match_different_kind(monkeypatch):
    import backend.services.memory_index as idx

    monkeypatch.setattr(idx, "_embed_sync", lambda _: None)
    idx.upsert_item(_make_item("subject", "body", kind="fact"))

    candidate = _make_item("subject", "body", kind="decision")
    # dedup_key includes kind, so these are different
    result = idx.find_similar(candidate, threshold=0.92)
    assert result is None


# ---------------------------------------------------------------------------
# search — ordering + fallback
# ---------------------------------------------------------------------------

def test_search_returns_closest_first(monkeypatch):
    """Item embedding closest to query should rank first."""
    import backend.services.memory_index as idx

    # "close" maps to _unit_vec(8,0); "far" to _unit_vec(8,1); query to 0.
    def controlled(text: str) -> list[float] | None:
        if "close" in text:
            return _unit_vec(8, 0)
        if "far" in text:
            return _unit_vec(8, 1)
        return _unit_vec(8, 0)   # query matches "close"

    monkeypatch.setattr(idx, "_embed_sync", controlled)

    idx.upsert_item(_make_item("close subject", "body for close"))
    idx.upsert_item(_make_item("far subject", "body for far"))

    results = idx.search("close subject query", k=2)
    assert len(results) >= 1
    assert results[0].subject == "close subject"


def test_search_text_fallback_like_match(monkeypatch):
    """When embed returns None, search falls back to LIKE on subject+body."""
    import backend.services.memory_index as idx

    monkeypatch.setattr(idx, "_embed_sync", lambda _: None)
    idx.upsert_item(_make_item("Python tips", "Use list comprehensions."))
    idx.upsert_item(_make_item("Rust memory safety", "No garbage collection."))

    results = idx.search("Python")
    subjects = [r.subject for r in results]
    assert "Python tips" in subjects
    assert "Rust memory safety" not in subjects


def test_search_text_fallback_body_match(monkeypatch):
    import backend.services.memory_index as idx

    monkeypatch.setattr(idx, "_embed_sync", lambda _: None)
    idx.upsert_item(_make_item("irrelevant subject", "cosine similarity is key"))

    results = idx.search("cosine")
    assert any(r.body == "cosine similarity is key" for r in results)


def test_search_empty_db_returns_empty(monkeypatch):
    _patch_embed(monkeypatch)
    import backend.services.memory_index as idx
    assert idx.search("anything") == []


def test_search_respects_k_limit(monkeypatch):
    _patch_embed(monkeypatch)
    import backend.services.memory_index as idx

    for i in range(10):
        idx.upsert_item(_make_item(f"subject {i}", f"body {i}"))

    results = idx.search("subject", k=3)
    assert len(results) <= 3


# ---------------------------------------------------------------------------
# Graceful degradation — upsert with embed returning None
# ---------------------------------------------------------------------------

def test_upsert_graceful_when_embed_unavailable(monkeypatch):
    """upsert_item succeeds and stores NULL embedding when Ollama is down."""
    import backend.services.memory_index as idx

    monkeypatch.setattr(idx, "_embed_sync", lambda _: None)
    item = _make_item("no-embed subject", "no-embed body")
    item_id = idx.upsert_item(item)

    assert item_id  # id still computed from sha1 of dedup_key
    items = idx.all_items()
    assert len(items) == 1
    assert items[0].embedding is None
    assert items[0].item_id == item_id


def test_upsert_graceful_item_id_stable_without_embed(monkeypatch):
    """item_id must be the same regardless of whether embeddings are available."""
    import backend.services.memory_index as idx

    monkeypatch.setattr(idx, "_embed_sync", lambda _: None)
    item_a = _make_item("stable subject", "stable body")
    id_no_embed = idx.upsert_item(item_a)

    monkeypatch.setattr(idx, "_db_initialized", False)
    import importlib, backend.services.memory_index
    # Reset DB to get a clean slate, then re-upsert with embeddings
    new_path = Path(str(idx.DB_PATH).replace(".db", "_b.db"))
    monkeypatch.setattr(idx, "DB_PATH", new_path)
    monkeypatch.setattr(idx, "_db_initialized", False)

    _patch_embed(monkeypatch)
    item_b = _make_item("stable subject", "stable body")
    id_with_embed = idx.upsert_item(item_b)

    assert id_no_embed == id_with_embed


# ---------------------------------------------------------------------------
# delete_item / delete_all (Settings privacy view)
# ---------------------------------------------------------------------------

def test_delete_item_removes_from_index(monkeypatch):
    import backend.services.memory_index as idx
    _patch_embed(monkeypatch, lambda _t: None)
    item_id = idx.upsert_item(_make_item("Fact A", "Body A."))
    idx.upsert_item(_make_item("Fact B", "Body B."))
    # delete_item returns the deleted body text (for notes scrubbing), None if absent
    assert idx.delete_item(item_id) == "Body A."
    remaining = {i.subject for i in idx.all_items()}
    assert remaining == {"Fact B"}
    assert idx.delete_item(item_id) is None  # already gone


def test_delete_all_wipes_everything(monkeypatch):
    import backend.services.memory_index as idx
    _patch_embed(monkeypatch, lambda _t: None)
    idx.upsert_item(_make_item("Fact A", "Body A."))
    idx.upsert_item(_make_item("Fact B", "Body B."))
    assert idx.delete_all() == 2
    assert idx.all_items() == []


def test_db_path_defaults_inside_data_root(monkeypatch, tmp_path):
    """Regression: the index must live in the app data root, never ~/.agentic-os."""
    import backend.services.memory_index as idx
    monkeypatch.setattr(idx, "DB_PATH", None)
    monkeypatch.setenv("ACADEMIC_OS_DATA", str(tmp_path))
    p = idx._db_path()
    assert str(p).startswith(str(tmp_path))
    assert ".agentic-os" not in str(p)
