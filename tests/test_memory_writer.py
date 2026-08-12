"""Tests for backend.services.memory_writer — Module B (Phase 1.1).

All tests run OFFLINE.  ``backend.vault.resolve_vault_path`` is monkeypatched
to return a pytest ``tmp_path``, so no iCloud file is ever touched.

Coverage:
- route() maps every known kind and unknown kinds → correct relpath.
- First file_item() call creates note with YAML frontmatter + bullet + daily log.
- Second file_item() on a *different* item appends and bumps last_updated.
- Re-filing the *same* item is idempotent (no duplicate bullet).
- item.vault_path is set after file_item().
- Tags and thread refs appear in the bullet.
- file_items() returns a de-duplicated relpath list covering kind-notes + log.
"""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from backend.services.memory_types import MemoryItem, MEMORY_KINDS
from backend.services.memory_writer import route, file_item, file_items


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def patch_vault(monkeypatch, tmp_path: Path):
    """Redirect all vault I/O to *tmp_path* so tests are hermetic."""
    monkeypatch.setattr("backend.vault.resolve_vault_path", lambda: tmp_path)
    return tmp_path


@pytest.fixture
def fact_item() -> MemoryItem:
    return MemoryItem(
        kind="fact",
        subject="Agentic OS uses hierarchical agents",
        body="The Agentic OS architecture relies on hierarchical agent coordination.",
        tags=["ai", "architecture"],
        source_thread="thread-001",
        ts="2026-06-26T12:00:00Z",
        confidence=0.9,
    )


@pytest.fixture
def fact_item2() -> MemoryItem:
    """A second, distinct fact item for the same kind-note."""
    return MemoryItem(
        kind="fact",
        subject="Vault is the storage layer",
        body="The Obsidian vault stores all durable memory as markdown files.",
        tags=["vault"],
        source_thread="thread-002",
        ts="2026-06-26T13:00:00Z",
        confidence=0.95,
    )


# ── route() ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("kind,expected_suffix", [
    ("fact",       "facts.md"),
    ("decision",   "decisions.md"),
    ("todo",       "todos.md"),
    ("preference", "preferences.md"),
    ("entity",     "entities.md"),
    ("event",      "events.md"),
])
def test_route_known_kinds(kind: str, expected_suffix: str):
    item = MemoryItem(kind=kind, subject="s", body="b")
    assert route(item).endswith(expected_suffix)


@pytest.mark.parametrize("kind", ["unknown", "", "bogus", "FACT"])
def test_route_unknown_kind_returns_misc(kind: str):
    item = MemoryItem(kind=kind, subject="s", body="b")
    assert route(item).endswith("misc.md")


def test_route_covers_all_memory_kinds():
    """Every value in MEMORY_KINDS must map to a non-misc note."""
    for kind in MEMORY_KINDS:
        item = MemoryItem(kind=kind, subject="s", body="b")
        assert "misc" not in route(item), f"kind={kind!r} unexpectedly maps to misc"


# ── file_item(): first write ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_file_item_creates_kind_note(fact_item: MemoryItem, tmp_path: Path):
    relpath = await file_item(fact_item)
    note = tmp_path / relpath
    assert note.exists(), f"Kind note not created at {note}"


@pytest.mark.asyncio
async def test_file_item_note_has_yaml_frontmatter(fact_item: MemoryItem, tmp_path: Path):
    relpath = await file_item(fact_item)
    content = (tmp_path / relpath).read_text()
    assert content.startswith("---"), "Note must start with YAML frontmatter"
    assert "last_updated:" in content


@pytest.mark.asyncio
async def test_file_item_frontmatter_has_today_utc(fact_item: MemoryItem, tmp_path: Path):
    today = time.strftime("%Y-%m-%d", time.gmtime())
    relpath = await file_item(fact_item)
    content = (tmp_path / relpath).read_text()
    assert f"last_updated: {today}" in content


@pytest.mark.asyncio
async def test_file_item_note_contains_bullet(fact_item: MemoryItem, tmp_path: Path):
    relpath = await file_item(fact_item)
    content = (tmp_path / relpath).read_text()
    assert fact_item.body in content
    assert fact_item.subject in content


@pytest.mark.asyncio
async def test_file_item_bullet_contains_thread_ref(fact_item: MemoryItem, tmp_path: Path):
    relpath = await file_item(fact_item)
    content = (tmp_path / relpath).read_text()
    assert f"^thread-{fact_item.source_thread}" in content


@pytest.mark.asyncio
async def test_file_item_bullet_contains_tags(fact_item: MemoryItem, tmp_path: Path):
    relpath = await file_item(fact_item)
    content = (tmp_path / relpath).read_text()
    for tag in fact_item.tags:
        assert f"#{tag}" in content


@pytest.mark.asyncio
async def test_file_item_creates_daily_log(fact_item: MemoryItem, tmp_path: Path):
    today = time.strftime("%Y-%m-%d", time.gmtime())
    await file_item(fact_item)
    log_path = tmp_path / f"notes/memory/log/{today}.md"
    assert log_path.exists(), f"Daily log not created at {log_path}"
    assert fact_item.body in log_path.read_text()


@pytest.mark.asyncio
async def test_file_item_daily_log_has_frontmatter(fact_item: MemoryItem, tmp_path: Path):
    today = time.strftime("%Y-%m-%d", time.gmtime())
    await file_item(fact_item)
    content = (tmp_path / f"notes/memory/log/{today}.md").read_text()
    assert "last_updated:" in content


@pytest.mark.asyncio
async def test_file_item_sets_vault_path(fact_item: MemoryItem):
    relpath = await file_item(fact_item)
    assert fact_item.vault_path == relpath
    assert relpath.endswith("facts.md")


@pytest.mark.asyncio
async def test_file_item_returns_correct_relpath(fact_item: MemoryItem):
    relpath = await file_item(fact_item)
    assert relpath == route(fact_item)


# ── file_item(): second write — new item ─────────────────────────────────────

@pytest.mark.asyncio
async def test_file_item_second_item_appends(
    fact_item: MemoryItem,
    fact_item2: MemoryItem,
    tmp_path: Path,
):
    relpath = await file_item(fact_item)
    await file_item(fact_item2)
    content = (tmp_path / relpath).read_text()
    assert fact_item.body in content
    assert fact_item2.body in content


@pytest.mark.asyncio
async def test_file_item_second_item_bumps_last_updated(
    fact_item: MemoryItem,
    fact_item2: MemoryItem,
    tmp_path: Path,
):
    today = time.strftime("%Y-%m-%d", time.gmtime())
    relpath = await file_item(fact_item)
    await file_item(fact_item2)
    content = (tmp_path / relpath).read_text()
    assert f"last_updated: {today}" in content


# ── file_item(): idempotency ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_file_item_idempotent_no_duplicate_bullet(
    fact_item: MemoryItem, tmp_path: Path
):
    relpath = await file_item(fact_item)
    await file_item(fact_item)  # re-file the exact same item
    content = (tmp_path / relpath).read_text()
    # body should appear exactly once
    assert content.count(fact_item.body) == 1


@pytest.mark.asyncio
async def test_file_item_idempotent_daily_log_no_duplicate(
    fact_item: MemoryItem, tmp_path: Path
):
    today = time.strftime("%Y-%m-%d", time.gmtime())
    await file_item(fact_item)
    await file_item(fact_item)
    log_content = (tmp_path / f"notes/memory/log/{today}.md").read_text()
    assert log_content.count(fact_item.body) == 1


@pytest.mark.asyncio
async def test_file_item_idempotent_last_updated_still_bumped(
    fact_item: MemoryItem, tmp_path: Path
):
    today = time.strftime("%Y-%m-%d", time.gmtime())
    relpath = await file_item(fact_item)
    await file_item(fact_item)
    content = (tmp_path / relpath).read_text()
    # last_updated should appear exactly once (not doubled)
    assert content.count("last_updated:") == 1
    assert f"last_updated: {today}" in content


# ── file_items() ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_file_items_returns_no_duplicates(tmp_path: Path):
    items = [
        MemoryItem(kind="fact", subject="F1", body="Body one.",
                   ts="2026-06-26T12:00:00Z", source_thread="t1"),
        MemoryItem(kind="fact", subject="F2", body="Body two.",
                   ts="2026-06-26T12:01:00Z", source_thread="t1"),
        MemoryItem(kind="decision", subject="D1", body="Decision body.",
                   ts="2026-06-26T12:02:00Z", source_thread="t1"),
    ]
    paths = await file_items(items)
    assert len(paths) == len(set(paths)), "Returned paths must be unique"


@pytest.mark.asyncio
async def test_file_items_includes_kind_notes(tmp_path: Path):
    items = [
        MemoryItem(kind="fact", subject="F", body="Fact body.",
                   ts="2026-06-26T12:00:00Z", source_thread="t1"),
        MemoryItem(kind="decision", subject="D", body="Decision body.",
                   ts="2026-06-26T12:00:00Z", source_thread="t1"),
    ]
    paths = await file_items(items)
    assert any("facts.md" in p for p in paths)
    assert any("decisions.md" in p for p in paths)


@pytest.mark.asyncio
async def test_file_items_includes_daily_log(tmp_path: Path):
    today = time.strftime("%Y-%m-%d", time.gmtime())
    items = [
        MemoryItem(kind="todo", subject="T", body="Do something.",
                   ts="2026-06-26T12:00:00Z", source_thread="t1"),
    ]
    paths = await file_items(items)
    assert any(today in p and "log" in p for p in paths)


@pytest.mark.asyncio
async def test_file_items_sets_vault_path_on_all(tmp_path: Path):
    items = [
        MemoryItem(kind="todo", subject="Task A", body="Do something.",
                   ts="2026-06-26T12:00:00Z", source_thread="t1"),
        MemoryItem(kind="event", subject="Event B", body="Something happened.",
                   ts="2026-06-26T12:00:00Z", source_thread="t1"),
    ]
    await file_items(items)
    assert all(it.vault_path != "" for it in items)


@pytest.mark.asyncio
async def test_file_items_empty_list_returns_empty(tmp_path: Path):
    paths = await file_items([])
    assert paths == []
