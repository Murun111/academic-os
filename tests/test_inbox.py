"""Tests for backend.services.inbox — Life Admin / Inbox (Panel E).

The inbox is a local JSONL of items the user wants to track. Each item
has: id, created_at, status (open/done/snoozed), priority (low/normal/high),
text, source (e.g. "reminders", "manual", "triage"), due (optional),
notes (optional).

Sync with Apple Reminders via remindctl is OPTIONAL — if remindctl
isn't installed or has no list configured, the service still works
locally and any items added are persisted in the vault.
"""
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from backend.services.inbox import (
    InboxItem,
    InboxService,
    InboxServiceError,
    PRIORITIES,
    STATUSES,
)


# === Construction ===

def test_constructs_with_data_dir(tmp_path: Path):
    svc = InboxService(data_dir=tmp_path)
    assert svc.data_dir == tmp_path


def test_creates_data_dir_if_missing(tmp_path: Path):
    target = tmp_path / "deep" / "nested" / "inbox"
    assert not target.exists()
    InboxService(data_dir=target)
    assert target.exists()


# === add() ===

def test_add_creates_first_item(tmp_path: Path):
    svc = InboxService(data_dir=tmp_path)
    item = svc.add(text="renew passport", priority="high")
    assert item.id is not None
    assert item.text == "renew passport"
    assert item.priority == "high"
    assert item.status == "open"
    assert item.created_at is not None


def test_add_assigns_unique_ids(tmp_path: Path):
    svc = InboxService(data_dir=tmp_path)
    a = svc.add(text="a")
    b = svc.add(text="b")
    assert a.id != b.id


def test_add_normalizes_priority(tmp_path: Path):
    svc = InboxService(data_dir=tmp_path)
    item = svc.add(text="x", priority="HIGH")
    assert item.priority == "high"  # normalized to lowercase


def test_add_rejects_invalid_priority(tmp_path: Path):
    svc = InboxService(data_dir=tmp_path)
    with pytest.raises(InboxServiceError, match="priority"):
        svc.add(text="x", priority="urgent")


def test_add_rejects_empty_text(tmp_path: Path):
    svc = InboxService(data_dir=tmp_path)
    with pytest.raises(InboxServiceError, match="text"):
        svc.add(text="")
    with pytest.raises(InboxServiceError, match="text"):
        svc.add(text="   ")


def test_add_persists_to_disk(tmp_path: Path):
    svc = InboxService(data_dir=tmp_path)
    item = svc.add(text="x", priority="normal")
    # Reload from disk
    svc2 = InboxService(data_dir=tmp_path)
    items = svc2.list_all()
    assert len(items) == 1
    assert items[0].id == item.id
    assert items[0].text == "x"


# === list_all() ===

def test_list_all_returns_empty_when_no_items(tmp_path: Path):
    svc = InboxService(data_dir=tmp_path)
    assert svc.list_all() == []


def test_list_all_returns_items_newest_first(tmp_path: Path):
    svc = InboxService(data_dir=tmp_path)
    a = svc.add(text="first")
    # Force a later timestamp for the second add
    import time; time.sleep(0.01)
    b = svc.add(text="second")
    items = svc.list_all()
    # Newest first by created_at
    assert items[0].id == b.id
    assert items[1].id == a.id


def test_list_filters_by_status(tmp_path: Path):
    svc = InboxService(data_dir=tmp_path)
    a = svc.add(text="a")
    b = svc.add(text="b")
    svc.mark_done(a.id)
    open_items = svc.list_all(status="open")
    done_items = svc.list_all(status="done")
    assert len(open_items) == 1
    assert open_items[0].id == b.id
    assert len(done_items) == 1
    assert done_items[0].id == a.id


# === mark_done() / reopen() ===

def test_mark_done_changes_status(tmp_path: Path):
    svc = InboxService(data_dir=tmp_path)
    a = svc.add(text="a")
    assert a.status == "open"
    updated = svc.mark_done(a.id)
    assert updated.status == "done"
    assert updated.completed_at is not None


def test_reopen_resets_to_open(tmp_path: Path):
    svc = InboxService(data_dir=tmp_path)
    a = svc.add(text="a")
    svc.mark_done(a.id)
    reverted = svc.reopen(a.id)
    assert reverted.status == "open"
    assert reverted.completed_at is None


def test_mark_done_idempotent(tmp_path: Path):
    """Marking done twice is fine; second is no-op."""
    svc = InboxService(data_dir=tmp_path)
    a = svc.add(text="a")
    svc.mark_done(a.id)
    again = svc.mark_done(a.id)
    assert again.status == "done"


def test_mark_done_unknown_id_raises(tmp_path: Path):
    svc = InboxService(data_dir=tmp_path)
    with pytest.raises(InboxServiceError, match="not found"):
        svc.mark_done("nonexistent-id")


# === update() ===

def test_update_text(tmp_path: Path):
    svc = InboxService(data_dir=tmp_path)
    a = svc.add(text="orig")
    updated = svc.update(a.id, text="new text")
    assert updated.text == "new text"


def test_update_priority(tmp_path: Path):
    svc = InboxService(data_dir=tmp_path)
    a = svc.add(text="x", priority="low")
    updated = svc.update(a.id, priority="high")
    assert updated.priority == "high"


def test_update_due_date(tmp_path: Path):
    svc = InboxService(data_dir=tmp_path)
    a = svc.add(text="x")
    due = date(2026, 7, 4)
    updated = svc.update(a.id, due=due)
    # `due` is stored as ISO string; compare via date.fromisoformat
    assert date.fromisoformat(updated.due) == due


def test_update_unknown_id_raises(tmp_path: Path):
    svc = InboxService(data_dir=tmp_path)
    with pytest.raises(InboxServiceError, match="not found"):
        svc.update("nonexistent", text="x")


def test_update_empty_raises(tmp_path: Path):
    """An update with no fields is a no-op-and-error."""
    svc = InboxService(data_dir=tmp_path)
    a = svc.add(text="x")
    with pytest.raises(InboxServiceError, match="no fields"):
        svc.update(a.id)


# === delete() ===

def test_delete_removes_item(tmp_path: Path):
    svc = InboxService(data_dir=tmp_path)
    a = svc.add(text="x")
    svc.delete(a.id)
    assert svc.list_all() == []


def test_delete_unknown_id_raises(tmp_path: Path):
    svc = InboxService(data_dir=tmp_path)
    with pytest.raises(InboxServiceError, match="not found"):
        svc.delete("nonexistent")


# === summary() ===

def test_summary_counts_by_status_and_priority(tmp_path: Path):
    svc = InboxService(data_dir=tmp_path)
    svc.add(text="low 1", priority="low")
    svc.add(text="low 2", priority="low")
    svc.add(text="high 1", priority="high")
    done = svc.add(text="done 1", priority="normal")
    svc.mark_done(done.id)

    s = svc.summary()
    assert s["total"] == 4
    assert s["open"] == 3
    assert s["done"] == 1
    assert s["by_priority"]["high"] == 1
    assert s["by_priority"]["low"] == 2


def test_summary_overdue_count(tmp_path: Path):
    svc = InboxService(data_dir=tmp_path)
    today = date.today()
    overdue = svc.add(text="overdue", due=today - timedelta(days=1))
    due_today = svc.add(text="today", due=today)
    future = svc.add(text="future", due=today + timedelta(days=7))
    no_due = svc.add(text="no due")

    s = svc.summary()
    assert s["overdue"] == 1
    assert s["due_today"] == 1
    assert s["due_soon"] == 2  # overdue + due_today


# === round-trip persistence ===

def test_items_survive_service_restart(tmp_path: Path):
    """After save + reload, all fields including completed_at are preserved."""
    svc1 = InboxService(data_dir=tmp_path)
    a = svc1.add(text="a", priority="high", due=date(2026, 7, 4))
    svc1.mark_done(a.id)

    svc2 = InboxService(data_dir=tmp_path)
    items = svc2.list_all()
    assert len(items) == 1
    assert items[0].priority == "high"
    # `due` is stored as ISO string; compare via date.fromisoformat
    assert date.fromisoformat(items[0].due) == date(2026, 7, 4)
    assert items[0].status == "done"
    assert items[0].completed_at is not None
