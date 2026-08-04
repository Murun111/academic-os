"""Documents Hub service — metadata tracking for application documents.

Tracks essays, CVs, transcripts, letters of recommendation, certificates,
and other application material as JSONL records. This is metadata
tracking only, NOT file storage: no uploads, no filesystem writes beyond
the JSONL ledger. `notes` can hold the actual essay text for MVP use.

Same rationale as inbox.py: a vault-resident ledger, one record per line,
crash-safe appends, atomic rewrites for updates.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional


KINDS = ("essay", "cv", "transcript", "lor", "certificate", "other")
STATUSES = ("draft", "in_review", "final")


class DocumentsServiceError(Exception):
    """Raised for bad input (invalid kind/status, empty title, etc)."""


@dataclass
class Document:
    id: str
    title: str
    kind: str
    created_at: str  # ISO 8601 datetime
    updated_at: str  # ISO 8601 datetime
    status: str = "draft"
    version: int = 1
    history: list[dict] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    linked_application_ids: list[str] = field(default_factory=list)
    notes: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Document":
        # Defensive: skip fields that aren't part of the schema.
        allowed = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in allowed})


class DocumentsService:
    """Local JSONL-backed document ledger.

    Records are append-only at the file level (each add() = one new
    line); updates rewrite the file (fine for our scale).
    """

    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._path = self.data_dir / "items.jsonl"

    def _read_all(self) -> list[Document]:
        if not self._path.exists():
            return []
        items: list[Document] = []
        with self._path.open() as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                    items.append(Document.from_dict(d))
                except (json.JSONDecodeError, TypeError) as e:
                    print(f"[documents] skipping malformed line: {e!r}")
                    continue
        return items

    def _write_all(self, items: list[Document]) -> None:
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

    def _validate_kind(self, kind: str) -> str:
        kind = (kind or "").strip().lower()
        if kind not in KINDS:
            raise DocumentsServiceError(
                f"invalid kind {kind!r}. Must be one of: {', '.join(KINDS)}"
            )
        return kind

    def _validate_status(self, status: str) -> str:
        status = (status or "draft").strip().lower()
        if status not in STATUSES:
            raise DocumentsServiceError(
                f"invalid status {status!r}. Must be one of: {', '.join(STATUSES)}"
            )
        return status

    def _validate_title(self, title: str) -> str:
        title = (title or "").strip()
        if not title:
            raise DocumentsServiceError("title is required and cannot be empty")
        return title

    # === CRUD ===

    def add(
        self,
        title: str,
        kind: str,
        status: str = "draft",
        tags: Optional[list[str]] = None,
        linked_application_ids: Optional[list[str]] = None,
        notes: str = "",
    ) -> Document:
        title = self._validate_title(title)
        kind = self._validate_kind(kind)
        status = self._validate_status(status)
        now = self._now_iso()
        item = Document(
            id=self._new_id(),
            title=title,
            kind=kind,
            created_at=now,
            updated_at=now,
            status=status,
            version=1,
            history=[],
            tags=list(tags or []),
            linked_application_ids=list(linked_application_ids or []),
            notes=notes,
        )
        with self._path.open("a") as f:
            f.write(json.dumps(item.to_dict(), separators=(",", ":")) + "\n")
        return item

    def list_all(
        self,
        kind: Optional[str] = None,
        tag: Optional[str] = None,
        application_id: Optional[str] = None,
    ) -> list[Document]:
        """Return all documents, optionally filtered. Newest-updated first."""
        items = self._read_all()
        if kind is not None:
            items = [i for i in items if i.kind == kind]
        if tag is not None:
            items = [i for i in items if tag in i.tags]
        if application_id is not None:
            items = [i for i in items if application_id in i.linked_application_ids]
        items.sort(key=lambda i: i.updated_at, reverse=True)
        return items

    def get(self, doc_id: str) -> Document:
        for i in self._read_all():
            if i.id == doc_id:
                return i
        raise KeyError(doc_id)

    def update(self, doc_id: str, **fields) -> Document:
        """Plain field edits (title, kind, status, tags, notes). No version bump."""
        items = self._read_all()
        for it in items:
            if it.id == doc_id:
                if "title" in fields and fields["title"] is not None:
                    it.title = self._validate_title(fields["title"])
                if "kind" in fields and fields["kind"] is not None:
                    it.kind = self._validate_kind(fields["kind"])
                if "status" in fields and fields["status"] is not None:
                    it.status = self._validate_status(fields["status"])
                if "tags" in fields and fields["tags"] is not None:
                    it.tags = list(fields["tags"])
                if "notes" in fields and fields["notes"] is not None:
                    it.notes = fields["notes"]
                it.updated_at = self._now_iso()
                self._write_all(items)
                return it
        raise KeyError(doc_id)

    def bump_version(self, doc_id: str, note: str) -> Document:
        items = self._read_all()
        for it in items:
            if it.id == doc_id:
                it.version += 1
                now = self._now_iso()
                it.history.append({"version": it.version, "note": note, "at": now})
                it.updated_at = now
                self._write_all(items)
                return it
        raise KeyError(doc_id)

    def delete(self, doc_id: str) -> None:
        items = self._read_all()
        new_items = [i for i in items if i.id != doc_id]
        if len(new_items) == len(items):
            raise KeyError(doc_id)
        self._write_all(new_items)

    def link(self, doc_id: str, application_id: str) -> Document:
        """Link a document to an application id. Idempotent."""
        items = self._read_all()
        for it in items:
            if it.id == doc_id:
                if application_id not in it.linked_application_ids:
                    it.linked_application_ids.append(application_id)
                    it.updated_at = self._now_iso()
                    self._write_all(items)
                return it
        raise KeyError(doc_id)

    def unlink(self, doc_id: str, application_id: str) -> Document:
        """Unlink a document from an application id. Idempotent."""
        items = self._read_all()
        for it in items:
            if it.id == doc_id:
                if application_id in it.linked_application_ids:
                    it.linked_application_ids.remove(application_id)
                    it.updated_at = self._now_iso()
                    self._write_all(items)
                return it
        raise KeyError(doc_id)
