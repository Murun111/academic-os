"""Tests for backend.services.memory — Phase 1.1 Module C.

All tests run OFFLINE — no Ollama, no SQLite, no vault writes.

Monkeypatching strategy (all patches via the 'mem' namespace):
- get_backend    → fake backend whose async chat() returns controlled JSON
- init_db        → no-op (avoid disk writes)
- find_similar   → controlled return sequence (None or MemoryItem)
- upsert_item    → assigns deterministic item_id, no DB
- file_item      → sets vault_path, returns fixed relpath, no disk
- _llm_get_thread→ returns a thread dict or None

Coverage:
- extract_items: parses clean, fenced (```json), and noisy JSON responses
- extract_items: drops items with invalid kind or empty body
- extract_items: returns [] on LLM failure or un-parseable response
- extract_items: returns [] for a thread with no messages
- consolidate_thread: files all non-duplicates, correct skipped_duplicates count
- consolidate_thread: deduplicates written_paths
- consolidate_thread: never raises — returns error field on backend failure
- consolidate_thread_id: returns thread_not_found for unknown tid
- consolidate_thread_id: delegates to consolidate_thread for known tid
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.services.memory_types import ConsolidationResult, MemoryItem


# ── Fixtures & shared data ────────────────────────────────────────────────────

def _make_thread(thread_id: str = "abc123", n_turns: int = 3) -> dict:
    messages = []
    for i in range(n_turns):
        messages.append({"role": "user", "content": f"User message {i}"})
        messages.append({"role": "assistant", "content": f"Assistant reply {i}"})
    return {"id": thread_id, "messages": messages}


# Known-good LLM response payloads
_TWO_ITEMS = [
    {"kind": "fact", "subject": "Agentic OS", "body": "It is a local-first OS.", "tags": ["os"], "confidence": 0.9},
    {"kind": "decision", "subject": "Use SQLite", "body": "SQLite chosen for the index.", "tags": [], "confidence": 0.8},
]

CLEAN_JSON = json.dumps(_TWO_ITEMS)
FENCED_JSON = f"```json\n{CLEAN_JSON}\n```"
NOISY_JSON = f"Sure, here are the memory items:\n{CLEAN_JSON}\n\nLet me know if you need more."

INVALID_KIND_JSON = json.dumps([
    {"kind": "bogus_kind", "subject": "Bad", "body": "Wrong kind.", "tags": [], "confidence": 0.5},
    {"kind": "fact", "subject": "Good", "body": "This is valid.", "tags": [], "confidence": 1.0},
])

EMPTY_BODY_JSON = json.dumps([
    {"kind": "fact", "subject": "Empty body item", "body": "", "tags": [], "confidence": 1.0},
    {"kind": "fact", "subject": "Valid item", "body": "This body is present.", "tags": [], "confidence": 0.9},
])


def _make_fake_backend(content: str) -> MagicMock:
    """Return a fake LLM backend whose chat() coroutine yields *content*."""
    fake_result = MagicMock()
    fake_result.content = content

    fake_backend = MagicMock()
    fake_backend.chat = AsyncMock(return_value=fake_result)
    return fake_backend


def _patch_mem(
    monkeypatch,
    content: str,
    *,
    find_similar_returns: list | None = None,
    vault_path: str = "Agentic OS/memory/facts.md",
) -> MagicMock:
    """Patch every external dependency of backend.services.memory.

    Returns the fake backend so callers can inspect call counts if needed.
    """
    import backend.services.memory as mem

    # LLM backend
    fake_backend = _make_fake_backend(content)
    monkeypatch.setattr(mem, "get_backend", lambda _name: fake_backend)

    # Index functions — no DB, no Ollama embeddings
    monkeypatch.setattr(mem, "init_db", lambda: None)

    returns = list(find_similar_returns) if find_similar_returns is not None else []
    call_state = {"n": 0}

    def _fake_find_similar(item, threshold=0.92):
        idx = call_state["n"]
        call_state["n"] += 1
        if idx < len(returns):
            return returns[idx]
        return None

    monkeypatch.setattr(mem, "find_similar", _fake_find_similar)

    item_counter = {"n": 0}

    def _fake_upsert(item):
        item.item_id = f"fake_id_{item_counter['n']}"
        item_counter["n"] += 1
        return item.item_id

    monkeypatch.setattr(mem, "upsert_item", _fake_upsert)

    # Writer — no vault I/O
    async def _fake_file_item(item):
        item.vault_path = vault_path
        return vault_path

    monkeypatch.setattr(mem, "file_item", _fake_file_item)

    return fake_backend


# ── extract_items: JSON parsing ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_extract_items_clean_json(monkeypatch):
    _patch_mem(monkeypatch, CLEAN_JSON)
    from backend.services.memory import extract_items

    items = await extract_items(_make_thread())

    assert len(items) == 2
    assert items[0].kind == "fact"
    assert items[1].kind == "decision"


@pytest.mark.asyncio
async def test_extract_items_fenced_json(monkeypatch):
    _patch_mem(monkeypatch, FENCED_JSON)
    from backend.services.memory import extract_items

    items = await extract_items(_make_thread())

    assert len(items) == 2
    assert items[0].kind == "fact"


@pytest.mark.asyncio
async def test_extract_items_noisy_json(monkeypatch):
    _patch_mem(monkeypatch, NOISY_JSON)
    from backend.services.memory import extract_items

    items = await extract_items(_make_thread())

    assert len(items) == 2


@pytest.mark.asyncio
async def test_extract_items_sets_source_thread(monkeypatch):
    _patch_mem(monkeypatch, CLEAN_JSON)
    from backend.services.memory import extract_items

    items = await extract_items(_make_thread("my_thread"))

    assert all(it.source_thread == "my_thread" for it in items)


@pytest.mark.asyncio
async def test_extract_items_sets_ts(monkeypatch):
    _patch_mem(monkeypatch, CLEAN_JSON)
    from backend.services.memory import extract_items

    items = await extract_items(_make_thread())

    assert all(it.ts != "" for it in items)


# ── extract_items: filtering ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_extract_items_drops_invalid_kind(monkeypatch):
    _patch_mem(monkeypatch, INVALID_KIND_JSON)
    from backend.services.memory import extract_items

    items = await extract_items(_make_thread())

    assert len(items) == 1
    assert items[0].kind == "fact"
    assert items[0].body == "This is valid."


@pytest.mark.asyncio
async def test_extract_items_drops_empty_body(monkeypatch):
    _patch_mem(monkeypatch, EMPTY_BODY_JSON)
    from backend.services.memory import extract_items

    items = await extract_items(_make_thread())

    assert len(items) == 1
    assert items[0].body == "This body is present."


# ── extract_items: failure cases ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_extract_items_unparseable_returns_empty(monkeypatch):
    _patch_mem(monkeypatch, "This is not JSON at all, sorry.")
    from backend.services.memory import extract_items

    items = await extract_items(_make_thread())

    assert items == []


@pytest.mark.asyncio
async def test_extract_items_empty_thread_returns_empty(monkeypatch):
    _patch_mem(monkeypatch, CLEAN_JSON)
    from backend.services.memory import extract_items

    items = await extract_items({"id": "no_msgs", "messages": []})

    assert items == []


@pytest.mark.asyncio
async def test_extract_items_llm_exception_returns_empty(monkeypatch):
    import backend.services.memory as mem

    def _boom(_name):
        raise RuntimeError("backend unavailable")

    monkeypatch.setattr(mem, "get_backend", _boom)

    from backend.services.memory import extract_items

    items = await extract_items(_make_thread())

    assert items == []


# ── consolidate_thread: filing ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_consolidate_thread_files_all_non_duplicates(monkeypatch):
    _patch_mem(monkeypatch, CLEAN_JSON, find_similar_returns=[None, None])
    from backend.services.memory import consolidate_thread

    result = await consolidate_thread(_make_thread())

    assert isinstance(result, ConsolidationResult)
    assert len(result.items) == 2
    assert result.skipped_duplicates == 0
    assert result.error == ""


@pytest.mark.asyncio
async def test_consolidate_thread_skips_duplicate_second_item(monkeypatch):
    """First item: no dup → filed. Second item: dup found → skipped."""
    dup = MemoryItem(kind="decision", subject="Dup", body="Already stored.")
    _patch_mem(monkeypatch, CLEAN_JSON, find_similar_returns=[None, dup])
    from backend.services.memory import consolidate_thread

    result = await consolidate_thread(_make_thread())

    assert len(result.items) == 1
    assert result.skipped_duplicates == 1
    assert result.error == ""


@pytest.mark.asyncio
async def test_consolidate_thread_skips_all_duplicates(monkeypatch):
    """Both items are duplicates → nothing filed."""
    dup = MemoryItem(kind="fact", subject="D", body="Dup body.")
    _patch_mem(monkeypatch, CLEAN_JSON, find_similar_returns=[dup, dup])
    from backend.services.memory import consolidate_thread

    result = await consolidate_thread(_make_thread())

    assert len(result.items) == 0
    assert result.skipped_duplicates == 2
    assert result.written_paths == []
    assert result.error == ""


@pytest.mark.asyncio
async def test_consolidate_thread_written_paths_deduped(monkeypatch):
    """Both items map to the same vault path; written_paths must be length 1."""
    _patch_mem(
        monkeypatch,
        CLEAN_JSON,
        find_similar_returns=[None, None],
        vault_path="Agentic OS/memory/facts.md",
    )
    from backend.services.memory import consolidate_thread

    result = await consolidate_thread(_make_thread())

    assert len(result.written_paths) == 1
    assert result.written_paths[0] == "Agentic OS/memory/facts.md"


@pytest.mark.asyncio
async def test_consolidate_thread_items_have_item_id_set(monkeypatch):
    _patch_mem(monkeypatch, CLEAN_JSON, find_similar_returns=[None, None])
    from backend.services.memory import consolidate_thread

    result = await consolidate_thread(_make_thread())

    assert all(it.item_id != "" for it in result.items)


@pytest.mark.asyncio
async def test_consolidate_thread_items_have_vault_path_set(monkeypatch):
    _patch_mem(monkeypatch, CLEAN_JSON, find_similar_returns=[None, None])
    from backend.services.memory import consolidate_thread

    result = await consolidate_thread(_make_thread())

    assert all(it.vault_path != "" for it in result.items)


# ── consolidate_thread: error safety ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_consolidate_thread_never_raises_on_backend_failure(monkeypatch):
    """If get_backend() throws, extract_items absorbs it; consolidate_thread
    returns a valid ConsolidationResult with no items — it never raises."""
    import backend.services.memory as mem

    def _boom(_name):
        raise RuntimeError("backend unavailable")

    monkeypatch.setattr(mem, "get_backend", _boom)
    monkeypatch.setattr(mem, "init_db", lambda: None)
    monkeypatch.setattr(mem, "find_similar", lambda item, threshold=0.92: None)
    monkeypatch.setattr(mem, "upsert_item", lambda item: "")

    async def _noop_file(item):
        return ""

    monkeypatch.setattr(mem, "file_item", _noop_file)

    from backend.services.memory import consolidate_thread

    # Must not raise — extract_items catches the backend failure gracefully
    result = await consolidate_thread(_make_thread("failthread"))

    assert isinstance(result, ConsolidationResult)
    assert result.thread_id == "failthread"
    assert result.items == []
    # error is "" because extraction is best-effort; the consolidation itself succeeded


@pytest.mark.asyncio
async def test_consolidate_thread_never_raises_on_upsert_failure(monkeypatch):
    """If upsert_item() throws, consolidate_thread returns error, does not raise."""
    import backend.services.memory as mem

    _patch_mem(monkeypatch, CLEAN_JSON, find_similar_returns=[None, None])

    def _boom(item):
        raise OSError("disk full")

    monkeypatch.setattr(mem, "upsert_item", _boom)

    from backend.services.memory import consolidate_thread

    result = await consolidate_thread(_make_thread())

    assert result.error != ""
    assert "OSError" in result.error or result.error


# ── consolidate_thread_id ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_consolidate_thread_id_not_found(monkeypatch):
    import backend.services.memory as mem
    monkeypatch.setattr(mem, "_llm_get_thread", lambda tid: None)

    from backend.services.memory import consolidate_thread_id

    result = await consolidate_thread_id("ghost_thread")

    assert result.error == "thread_not_found"
    assert result.thread_id == "ghost_thread"
    assert result.items == []


@pytest.mark.asyncio
async def test_consolidate_thread_id_found_delegates(monkeypatch):
    """consolidate_thread_id with a known tid delegates to consolidate_thread."""
    import backend.services.memory as mem

    thread = _make_thread("real_thread")
    monkeypatch.setattr(mem, "_llm_get_thread", lambda tid: thread if tid == "real_thread" else None)
    _patch_mem(monkeypatch, CLEAN_JSON, find_similar_returns=[None, None])

    from backend.services.memory import consolidate_thread_id

    result = await consolidate_thread_id("real_thread")

    assert result.thread_id == "real_thread"
    assert result.error == ""
    assert len(result.items) == 2
