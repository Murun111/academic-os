"""Shared data types for the memory subsystem (Phase 1.1).

This module is the *interface spine* between the memory index, the memory
writer, and the consolidation orchestrator. It has no behavior and no
dependencies so every memory module can import it without cycles.

See: docs/specs/phase-1.1-memory-consolidation.md
"""
from __future__ import annotations

from dataclasses import dataclass, field

# The kinds of durable memory we extract from a conversation.
MEMORY_KINDS: tuple[str, ...] = (
    "fact",        # a stable piece of knowledge about the user/world
    "decision",    # a choice that was made (and ideally why)
    "todo",        # an actionable item / commitment
    "preference",  # how the user likes things done
    "entity",      # a person/project/org/tool worth tracking
    "event",       # something that happened at a point in time
)


@dataclass
class MemoryItem:
    """One durable unit of memory distilled from a conversation."""

    kind: str                          # one of MEMORY_KINDS
    subject: str                       # short title, e.g. "Agentic OS architecture"
    body: str                          # the durable statement (1–3 sentences)
    tags: list[str] = field(default_factory=list)
    source_thread: str = ""            # thread id this came from
    ts: str = ""                       # ISO-8601 UTC, e.g. 2026-06-26T12:00:00Z
    confidence: float = 1.0            # 0..1
    item_id: str = ""                  # stable hash (set by index.upsert_item)
    vault_path: str = ""               # relpath it was filed to (set by writer)
    embedding: list[float] | None = None  # set by index when embeddings available

    def dedup_key(self) -> str:
        """Canonical string used to derive a stable item_id and for text dedup."""
        return f"{self.kind}|{self.subject.strip().lower()}|{self.body.strip().lower()}"


@dataclass
class ConsolidationResult:
    """Outcome of consolidating one thread into memory."""

    thread_id: str
    items: list = field(default_factory=list)           # list[MemoryItem] actually filed
    written_paths: list = field(default_factory=list)   # vault relpaths touched
    skipped_duplicates: int = 0
    error: str = ""

    def to_dict(self) -> dict:
        return {
            "thread_id": self.thread_id,
            "items": [
                {
                    "kind": it.kind,
                    "subject": it.subject,
                    "body": it.body,
                    "tags": it.tags,
                    "ts": it.ts,
                    "item_id": it.item_id,
                    "vault_path": it.vault_path,
                }
                for it in self.items
            ],
            "written_paths": self.written_paths,
            "skipped_duplicates": self.skipped_duplicates,
            "error": self.error,
        }
