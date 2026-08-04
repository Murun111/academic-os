"""Inbox service — Life Admin / Panel E's backend.

The inbox is a local JSONL of items the user wants to track. Each item
has: id, created_at, status, priority, text, source, due (optional),
notes (optional), completed_at (set when status='done').

Why JSONL, not SQLite: same rationale as the money service. This is
a vault-resident ledger the user can `cat`, `grep`, and edit by hand.
Crash-safe (one item per line, atomic appends). Git-trackable.

Sync with Apple Reminders (via remindctl) is OPTIONAL and lives in
a separate `reminders_sync.py` module. The service works fully without
it — sync just becomes a one-way push of `open` items to the
configured Reminders list.
"""
from __future__ import annotations

import json
import os
import uuid
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from dotenv import dotenv_values


_ENV_PATH = Path(__file__).parent.parent.parent / "backend" / ".env"
if _ENV_PATH.exists():
    _ENV = dotenv_values(_ENV_PATH)
else:
    _ENV = os.environ


PRIORITIES = ("low", "normal", "high")
STATUSES = ("open", "done", "snoozed")


class InboxServiceError(Exception):
    """Raised when the inbox service can't complete an operation."""


@dataclass
class InboxItem:
    id: str
    text: str
    created_at: str  # ISO 8601 datetime
    status: str = "open"
    priority: str = "normal"
    source: str = "manual"
    due: Optional[str] = None  # ISO 8601 date
    completed_at: Optional[str] = None  # ISO 8601 datetime
    notes: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "InboxItem":
        # Defensive: skip fields that aren't part of the schema.
        allowed = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in allowed})


class InboxService:
    """Local JSONL-backed inbox.

    Items are append-only at the file level (each add() = one new line),
    updates rewrite the file (rare, fine for our scale).
    """

    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._path = self.data_dir / "items.jsonl"

    def _read_all(self) -> list[InboxItem]:
        if not self._path.exists():
            return []
        items: list[InboxItem] = []
        with self._path.open() as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                    items.append(InboxItem.from_dict(d))
                except (json.JSONDecodeError, TypeError) as e:
                    # Skip malformed lines silently — same policy as money
                    print(f"[inbox] skipping malformed line: {e!r}")
                    continue
        return items

    def _write_all(self, items: list[InboxItem]) -> None:
        """Atomic rewrite — write to .tmp, rename over the real file."""
        tmp = self._path.with_suffix(".jsonl.tmp")
        with tmp.open("w") as f:
            for it in items:
                f.write(json.dumps(it.to_dict(), separators=(",", ":")) + "\n")
        tmp.replace(self._path)

    def _new_id(self) -> str:
        return uuid.uuid4().hex[:12]

    def _now_iso(self) -> str:
        return datetime.now().isoformat(timespec="microseconds")

    def _validate_priority(self, p: str) -> str:
        p = (p or "normal").strip().lower()
        if p not in PRIORITIES:
            raise InboxServiceError(
                f"invalid priority {p!r}. Must be one of: {', '.join(PRIORITIES)}"
            )
        return p

    def _validate_status(self, s: str) -> str:
        s = (s or "open").strip().lower()
        if s not in STATUSES:
            raise InboxServiceError(
                f"invalid status {s!r}. Must be one of: {', '.join(STATUSES)}"
            )
        return s

    def _validate_text(self, text: str) -> str:
        text = (text or "").strip()
        if not text:
            raise InboxServiceError("text is required and cannot be empty")
        return text

    # === CRUD ===

    def add(
        self,
        text: str,
        priority: str = "normal",
        source: str = "manual",
        due: Optional[date] = None,
        notes: str = "",
    ) -> InboxItem:
        text = self._validate_text(text)
        priority = self._validate_priority(priority)
        if due is not None and not isinstance(due, date):
            raise InboxServiceError("due must be a datetime.date or None")
        item = InboxItem(
            id=self._new_id(),
            text=text,
            created_at=self._now_iso(),
            status="open",
            priority=priority,
            source=source,
            due=due.isoformat() if due else None,
            notes=notes,
        )
        with self._path.open("a") as f:
            f.write(json.dumps(item.to_dict(), separators=(",", ":")) + "\n")
        return item

    def list_all(self, status: Optional[str] = None) -> list[InboxItem]:
        """Return all items, optionally filtered by status.

        Sorted newest-first by created_at.
        """
        items = self._read_all()
        if status is not None:
            status = self._validate_status(status)
            items = [i for i in items if i.status == status]
        items.sort(key=lambda i: i.created_at, reverse=True)
        return items

    def get(self, item_id: str) -> InboxItem:
        for i in self._read_all():
            if i.id == item_id:
                return i
        raise InboxServiceError(f"item {item_id!r} not found")

    def update(
        self,
        item_id: str,
        text: Optional[str] = None,
        priority: Optional[str] = None,
        due: Optional[date] = None,
        notes: Optional[str] = None,
    ) -> InboxItem:
        items = self._read_all()
        for i, it in enumerate(items):
            if it.id == item_id:
                if text is not None:
                    it.text = self._validate_text(text)
                if priority is not None:
                    it.priority = self._validate_priority(priority)
                if due is not None:
                    if not isinstance(due, date):
                        raise InboxServiceError("due must be a datetime.date or None")
                    it.due = due.isoformat()
                if notes is not None:
                    it.notes = notes
                if (
                    text is None
                    and priority is None
                    and due is None
                    and notes is None
                ):
                    raise InboxServiceError(
                        "update() called with no fields to change"
                    )
                self._write_all(items)
                return it
        raise InboxServiceError(f"item {item_id!r} not found")

    def mark_done(self, item_id: str) -> InboxItem:
        items = self._read_all()
        for it in items:
            if it.id == item_id:
                it.status = "done"
                it.completed_at = self._now_iso()
                self._write_all(items)
                return it
        raise InboxServiceError(f"item {item_id!r} not found")

    def reopen(self, item_id: str) -> InboxItem:
        items = self._read_all()
        for it in items:
            if it.id == item_id:
                it.status = "open"
                it.completed_at = None
                self._write_all(items)
                return it
        raise InboxServiceError(f"item {item_id!r} not found")

    def delete(self, item_id: str) -> None:
        items = self._read_all()
        new_items = [i for i in items if i.id != item_id]
        if len(new_items) == len(items):
            raise InboxServiceError(f"item {item_id!r} not found")
        self._write_all(new_items)

    # === Aggregates ===

    def summary(self) -> dict:
        items = self._read_all()
        today = date.today()
        open_items = [i for i in items if i.status == "open"]
        done_items = [i for i in items if i.status == "done"]
        by_priority: dict[str, int] = {p: 0 for p in PRIORITIES}
        for i in open_items:
            by_priority[i.priority] = by_priority.get(i.priority, 0) + 1
        overdue = 0
        due_today = 0
        for i in open_items:
            if i.due is None:
                continue
            d = date.fromisoformat(i.due)
            if d < today:
                overdue += 1
            elif d == today:
                due_today += 1
        return {
            "total": len(items),
            "open": len(open_items),
            "done": len(done_items),
            "overdue": overdue,
            "due_today": due_today,
            "due_soon": overdue + due_today,
            "by_priority": by_priority,
        }
