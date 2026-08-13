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
import os
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
    content: str = ""  # the essay text itself — the app is the editor, not a filing cabinet
    files: list = field(default_factory=list)  # [{name, size, added_at}] — stored under files/<doc_id>/

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
                if "content" in fields and fields["content"] is not None:
                    it.content = fields["content"]
                it.updated_at = self._now_iso()
                self._write_all(items)
                return it
        raise KeyError(doc_id)

    def bump_version(self, doc_id: str, note: str) -> Document:
        """Snapshot the current draft text into history and bump the number."""
        items = self._read_all()
        for it in items:
            if it.id == doc_id:
                it.version += 1
                now = self._now_iso()
                it.history.append({"version": it.version, "note": note, "at": now,
                                   "content": it.content})
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
        # cascade: drop this document's attached files too
        import shutil

        shutil.rmtree(self._files_dir(doc_id), ignore_errors=True)

    # === file attachments ===

    MAX_FILE_BYTES = 25 * 1024 * 1024  # a transcript PDF is ~1MB; 25MB is generous

    def _files_dir(self, doc_id: str) -> Path:
        return self.data_dir / "files" / doc_id

    @staticmethod
    def _safe_filename(name: str) -> str:
        name = (name or "").strip()
        if not name or "/" in name or "\\" in name or ".." in name or name.startswith("."):
            raise DocumentsServiceError("invalid filename")
        return name

    def attach_file(self, doc_id: str, filename: str, data: bytes) -> Document:
        """Store a file for this document. Name collisions get a numeric suffix.

        Write order: bytes go to a .tmp file first, then the JSONL record is
        updated and persisted (with the final, collision-resolved name), and
        only once that succeeds does the tmp get renamed into place. This
        way a crash before the JSONL write leaves only an inert .tmp file
        (no orphan entry a student could see and re-download), rather than
        a real file with no metadata pointing at it. Tradeoff: for the brief
        window between _write_all() and os.replace(), the persisted metadata
        names a file that doesn't exist under its final name yet — acceptable
        since the read path (file_path()) already 404s gracefully on a
        missing file.
        """
        if len(data) > self.MAX_FILE_BYTES:
            raise DocumentsServiceError(
                f"file too large ({len(data)} bytes; max {self.MAX_FILE_BYTES})"
            )
        filename = self._safe_filename(filename)
        items = self._read_all()
        for it in items:
            if it.id == doc_id:
                fdir = self._files_dir(doc_id)
                fdir.mkdir(parents=True, exist_ok=True)
                target = fdir / filename
                stem, suffix = target.stem, target.suffix
                n = 1
                while target.exists():
                    target = fdir / f"{stem}-{n}{suffix}"
                    n += 1
                tmp = fdir / f".{target.name}.uploading"
                tmp.write_bytes(data)
                it.files.append({
                    "name": target.name,
                    "size": len(data),
                    "added_at": self._now_iso(),
                })
                it.updated_at = self._now_iso()
                try:
                    self._write_all(items)
                except Exception:
                    it.files.pop()
                    tmp.unlink(missing_ok=True)
                    raise
                os.replace(tmp, target)
                return it
        raise KeyError(doc_id)

    def file_path(self, doc_id: str, filename: str) -> Path:
        """Absolute path of an attached file, for serving. Raises on unknown."""
        filename = self._safe_filename(filename)
        doc = self.get(doc_id)
        if not any(f["name"] == filename for f in doc.files):
            raise KeyError(filename)
        p = self._files_dir(doc_id) / filename
        if not p.is_file():
            raise KeyError(filename)
        return p

    def remove_file(self, doc_id: str, filename: str) -> Document:
        filename = self._safe_filename(filename)
        items = self._read_all()
        for it in items:
            if it.id == doc_id:
                if not any(f["name"] == filename for f in it.files):
                    raise KeyError(filename)
                it.files = [f for f in it.files if f["name"] != filename]
                (self._files_dir(doc_id) / filename).unlink(missing_ok=True)
                it.updated_at = self._now_iso()
                self._write_all(items)
                return it
        raise KeyError(doc_id)

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
