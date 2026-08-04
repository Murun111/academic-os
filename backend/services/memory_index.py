"""SQLite-backed memory index with local Ollama embeddings (Phase 1.1 Module A).

Public interface:
    DB_PATH        — default storage path (~/.agentic-os/memory/index.db)
    init_db()      — create directory + table
    embed()        — async; None on any failure (graceful degradation)
    upsert_item()  — sha1(dedup_key) → item_id; stores embedding best-effort
    find_similar() — cosine dedup, falls back to text match when no embeddings
    search()       — cosine ranking or LIKE fallback; top-k results
    all_items()    — return every stored MemoryItem
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from pathlib import Path

import httpx

from backend.services.memory_types import MemoryItem

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DB_PATH: Path = Path.home() / ".agentic-os" / "memory" / "index.db"

_OLLAMA_URL = "http://127.0.0.1:11434/api/embeddings"
_OLLAMA_MODEL = "nomic-embed-text"
_EMBED_TIMEOUT = 5.0

# ---------------------------------------------------------------------------
# Lazy-init sentinel
# ---------------------------------------------------------------------------

_db_initialized = False


def _ensure_db() -> None:
    global _db_initialized
    if not _db_initialized:
        init_db()
        _db_initialized = True


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS memory_items (
    item_id       TEXT PRIMARY KEY,
    kind          TEXT NOT NULL,
    subject       TEXT NOT NULL,
    body          TEXT NOT NULL,
    tags          TEXT NOT NULL DEFAULT '[]',
    source_thread TEXT NOT NULL DEFAULT '',
    ts            TEXT NOT NULL DEFAULT '',
    confidence    REAL NOT NULL DEFAULT 1.0,
    vault_path    TEXT NOT NULL DEFAULT '',
    embedding     TEXT
);
"""


def init_db() -> None:
    """Create the DB directory and table if not already present."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.executescript(_SCHEMA)


# ---------------------------------------------------------------------------
# Embedding helpers
# ---------------------------------------------------------------------------

def _embed_sync(text: str) -> list[float] | None:
    """Call Ollama synchronously; return None on any failure."""
    try:
        with httpx.Client(timeout=_EMBED_TIMEOUT) as client:
            r = client.post(
                _OLLAMA_URL,
                json={
                    "model": _OLLAMA_MODEL,
                    "prompt": text,
                    "keep_alive": os.environ.get("OLLAMA_KEEP_ALIVE", "5m"),
                },
            )
            r.raise_for_status()
            return r.json()["embedding"]
    except Exception:
        return None


def _embed_batch_sync(texts: list[str]) -> list[list[float] | None]:
    """Batch-embed via Ollama's /api/embed (input: [...]). Much faster than N single
    calls for pre-warming a large index. Returns one vector per input (None on total
    failure). Falls back to per-item _embed_sync if the batch endpoint errors."""
    if not texts:
        return []
    url = _OLLAMA_URL.rsplit("/", 1)[0] + "/embed"
    try:
        with httpx.Client(timeout=max(_EMBED_TIMEOUT, 60.0)) as client:
            r = client.post(url, json={
                "model": _OLLAMA_MODEL, "input": texts,
                "keep_alive": os.environ.get("OLLAMA_KEEP_ALIVE", "5m"),
            })
            r.raise_for_status()
            embs = r.json().get("embeddings") or []
            if len(embs) == len(texts):
                return embs
    except Exception:
        pass
    return [_embed_sync(t) for t in texts]  # degrade to per-item


async def embed(text: str) -> list[float] | None:
    """Async public interface.  Delegates to _embed_sync; returns None on failure."""
    return _embed_sync(text)


def _cosine(a: list[float], b: list[float]) -> float:
    """Pure-Python cosine similarity (no numpy)."""
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(x * x for x in b) ** 0.5
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


# ---------------------------------------------------------------------------
# Row <-> MemoryItem conversion
# ---------------------------------------------------------------------------

def _row_to_item(row: sqlite3.Row) -> MemoryItem:
    embedding = json.loads(row["embedding"]) if row["embedding"] else None
    return MemoryItem(
        item_id=row["item_id"],
        kind=row["kind"],
        subject=row["subject"],
        body=row["body"],
        tags=json.loads(row["tags"]),
        source_thread=row["source_thread"],
        ts=row["ts"],
        confidence=row["confidence"],
        vault_path=row["vault_path"],
        embedding=embedding,
    )


def _fetch_all_rows(exclude_id: str = "") -> list[sqlite3.Row]:
    """Return all rows, optionally excluding one item_id."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        if exclude_id:
            return conn.execute(
                "SELECT * FROM memory_items WHERE item_id != ?", (exclude_id,)
            ).fetchall()
        return conn.execute("SELECT * FROM memory_items").fetchall()


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def upsert_item(item: MemoryItem) -> str:
    """Compute item_id = sha1(dedup_key()), store item, return item_id.

    Embedding is stored best-effort; NULL is written when Ollama is unavailable.
    """
    _ensure_db()
    item_id = hashlib.sha1(item.dedup_key().encode()).hexdigest()
    item.item_id = item_id

    embedding = _embed_sync(item.dedup_key())
    item.embedding = embedding

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO memory_items
                (item_id, kind, subject, body, tags, source_thread, ts,
                 confidence, vault_path, embedding)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item_id,
                item.kind,
                item.subject,
                item.body,
                json.dumps(item.tags),
                item.source_thread,
                item.ts,
                item.confidence,
                item.vault_path,
                json.dumps(embedding) if embedding is not None else None,
            ),
        )
    return item_id


def find_similar(
    item: MemoryItem, threshold: float = 0.92
) -> MemoryItem | None:
    """Return the stored item most similar to *item*, or None.

    Uses cosine similarity when embeddings are available; falls back to exact
    dedup_key() text match when neither the item nor any stored entry has an
    embedding (graceful degradation).
    """
    _ensure_db()
    rows = _fetch_all_rows(exclude_id=item.item_id)

    # Try embedding-based similarity.
    query_vec: list[float] | None = item.embedding or _embed_sync(item.dedup_key())

    if query_vec is not None:
        best_score = -1.0
        best_match: MemoryItem | None = None
        for row in rows:
            stored_vec = json.loads(row["embedding"]) if row["embedding"] else None
            if stored_vec is None:
                continue
            score = _cosine(query_vec, stored_vec)
            if score > best_score:
                best_score = score
                best_match = _row_to_item(row)
        if best_match is not None and best_score >= threshold:
            return best_match
        return None

    # Fallback: exact dedup_key text match.
    target_key = item.dedup_key()
    for row in rows:
        stored_item = _row_to_item(row)
        if stored_item.dedup_key() == target_key:
            return stored_item
    return None


def search(query: str, k: int = 8) -> list[MemoryItem]:
    """Return up to *k* items most relevant to *query*.

    Ranks by cosine similarity when embeddings are available; falls back to a
    LIKE match on subject + body columns.
    """
    _ensure_db()
    rows = _fetch_all_rows()

    if not rows:
        return []

    query_vec = _embed_sync(query)

    if query_vec is not None:
        scored: list[tuple[float, sqlite3.Row]] = []
        for row in rows:
            stored_vec = json.loads(row["embedding"]) if row["embedding"] else None
            score = _cosine(query_vec, stored_vec) if stored_vec is not None else 0.0
            scored.append((score, row))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [_row_to_item(r) for _, r in scored[:k]]

    # Fallback: LIKE on subject + body.
    pattern = f"%{query}%"
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        like_rows = conn.execute(
            "SELECT * FROM memory_items WHERE subject LIKE ? OR body LIKE ? LIMIT ?",
            (pattern, pattern, k),
        ).fetchall()
    return [_row_to_item(r) for r in like_rows]


def all_items() -> list[MemoryItem]:
    """Return every stored MemoryItem."""
    _ensure_db()
    return [_row_to_item(r) for r in _fetch_all_rows()]
