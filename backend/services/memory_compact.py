"""Memory compaction — the *distillation* pass over the memory spine.

Karpathy's memory discipline: capture is cheap, but value comes from the
periodic pass that turns an ever-growing log into a small set of durable,
high-signal notes. This module is that pass — the "memory manager" that
keeps the active spine small enough to page into a context window.

It operates ONLY on the distilled kind-notes
(``Agentic OS/memory/{facts,decisions,todos,preferences,entities,events}.md``).
It NEVER touches ``memory/log/`` — the daily log is the raw, append-only
audit trail (Karpathy's running log) and is left intact by design.

Per file, in order:
  1. parse bullets back into MemoryItems
  2. drop noise          → archive (reason: noise)
  3. drop aged items     → archive (reason: aged, > MEMORY_TTL_DAYS)
  4. supersede duplicate subjects (keep newest)  → archive (reason: superseded)
  5. merge near-duplicate bodies via embeddings  → archive (reason: similar)
  6. rewrite the note with the survivors (newest first)

Nothing is ever deleted: every removed bullet is appended to
``Agentic OS/memory/_archive/<file>`` so compaction is fully reversible.
Finally, ``_index.md`` (a map-of-content) is regenerated.

Public interface:
    compact_all() -> dict      # async; summary of what changed
"""
from __future__ import annotations

import logging
import os
import re
import time
from datetime import datetime, timezone

from backend.services.memory import is_noise
from backend.services.memory_types import MemoryItem
from backend.services.memory_writer import _make_bullet, normalize_tag
from backend.services.tools import vault_read, vault_write

log = logging.getLogger(__name__)

_MEMORY_BASE = "Agentic OS/memory"
_ARCHIVE_DIR = f"{_MEMORY_BASE}/_archive"
_INDEX_PATH = f"{_MEMORY_BASE}/_index.md"

# file basename -> memory kind
_FILE_TO_KIND: dict[str, str] = {
    "facts.md": "fact",
    "decisions.md": "decision",
    "todos.md": "todo",
    "preferences.md": "preference",
    "entities.md": "entity",
    "events.md": "event",
}

# Items older than this are archived (reversibly). Generous default so we
# distil duplicates aggressively but only age out genuinely stale state.
_TTL_DAYS: int = int(os.environ.get("MEMORY_TTL_DAYS", "180"))

# Cosine threshold for cross-subject near-duplicate merge. Calibrated for
# nomic-embed-text, whose paraphrase scores cluster ~0.85–0.90 while genuinely
# distinct facts stay below ~0.65 — so 0.82 sits in the gap: it collapses
# paraphrases ("COO owns daily ops" said two ways) without merging distinct
# facts (net worth vs cashflow). Override via MEMORY_COMPACT_SIM if you swap
# the embedding model.
_SIM_THRESHOLD: float = float(os.environ.get("MEMORY_COMPACT_SIM", "0.82"))

# `- [ts] **subject** — body  ^thread-... #tags`
_BULLET_RE = re.compile(r"^- \[(?P<ts>[^\]]*)\]\s+\*\*(?P<subject>.*?)\*\*\s+[—-]\s+(?P<rest>.*)$")


# ── Parsing ──────────────────────────────────────────────────────────────────

def parse_bullet(line: str, kind: str) -> MemoryItem | None:
    """Parse one markdown bullet back into a MemoryItem, or None if it isn't one."""
    m = _BULLET_RE.match(line.rstrip())
    if not m:
        return None
    ts = m.group("ts").strip()
    subject = m.group("subject").strip()
    rest = m.group("rest")

    # Split off the `^thread-...` marker; everything before it is the body,
    # everything after holds the thread id and trailing #tags.
    parts = re.split(r"\^thread-", rest, maxsplit=1)
    body = parts[0].strip()
    tail = parts[1] if len(parts) > 1 else ""
    thread = ""
    if tail:
        tm = re.match(r"(\S+)", tail)
        thread = tm.group(1) if tm else ""
    tag_src = tail or body
    tags = [normalize_tag(t) for t in re.findall(r"#([A-Za-z0-9][\w/-]*)", tag_src)]
    tags = [t for t in tags if t]
    if not tail:  # no thread marker → strip any trailing hashtags off the body
        body = re.sub(r"(?:\s+#[A-Za-z0-9][\w/-]*)+\s*$", "", body).strip()
    if not body:
        return None
    return MemoryItem(kind=kind, subject=subject, body=body, tags=tags,
                      source_thread=thread, ts=ts, confidence=1.0)


def _parse_note(content: str, kind: str) -> list[MemoryItem]:
    return [it for ln in content.splitlines()
            if (it := parse_bullet(ln, kind)) is not None]


# ── Time helpers ─────────────────────────────────────────────────────────────

def _age_days(ts: str) -> float:
    """Age of an ISO-8601 UTC timestamp in days; 0.0 if unparseable (keep it)."""
    try:
        dt = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return 0.0
    return (datetime.now(timezone.utc) - dt).total_seconds() / 86400.0


# ── Compaction core ──────────────────────────────────────────────────────────

def _compact_items(items: list[MemoryItem]) -> tuple[list[MemoryItem], list[tuple[MemoryItem, str]]]:
    """Return (survivors newest-first, [(archived_item, reason), ...])."""
    archived: list[tuple[MemoryItem, str]] = []

    # 1. noise
    kept: list[MemoryItem] = []
    for it in items:
        if is_noise(it.subject, it.body):
            archived.append((it, "noise"))
        else:
            kept.append(it)

    # 2. age decay
    fresh: list[MemoryItem] = []
    for it in kept:
        if _age_days(it.ts) > _TTL_DAYS:
            archived.append((it, "aged"))
        else:
            fresh.append(it)

    # 3. supersede duplicate subjects — keep the newest ts per normalized subject
    fresh.sort(key=lambda it: it.ts, reverse=True)
    by_subject: dict[str, MemoryItem] = {}
    survivors: list[MemoryItem] = []
    for it in fresh:
        key = it.subject.strip().lower()
        if key in by_subject:
            archived.append((it, "superseded"))
            continue
        by_subject[key] = it
        survivors.append(it)

    # 4. embedding-based near-duplicate merge across different subjects
    survivors = _merge_similar(survivors, archived)

    survivors.sort(key=lambda it: it.ts, reverse=True)
    return survivors, archived


def _merge_similar(
    survivors: list[MemoryItem],
    archived: list[tuple[MemoryItem, str]],
) -> list[MemoryItem]:
    """Drop later survivors whose body is ~identical to an earlier kept one.

    Best-effort: if embeddings are unavailable (Ollama down / no model), this
    is a no-op and subject-level supersession is the only dedup.
    """
    try:
        from backend.services.memory_index import _cosine, _embed_sync
    except Exception:  # noqa: BLE001
        return survivors

    kept: list[MemoryItem] = []
    kept_vecs: list[list[float]] = []
    for it in survivors:
        vec = _embed_sync(it.body)
        if vec is None:
            kept.append(it)
            continue
        dup = False
        for kv in kept_vecs:
            if _cosine(vec, kv) >= _SIM_THRESHOLD:
                dup = True
                break
        if dup:
            archived.append((it, "similar"))
        else:
            kept.append(it)
            kept_vecs.append(vec)
    return kept


# ── Vault I/O ────────────────────────────────────────────────────────────────

def _rebuild_note(kind: str, survivors: list[MemoryItem], today: str) -> str:
    heading = kind.capitalize()
    lines = [f"---\nlast_updated: {today}\n---\n", f"# {heading}\n"]
    lines += [_make_bullet(it) for it in survivors]
    return "\n".join(lines) + "\n"


async def _archive(filename: str, removed: list[tuple[MemoryItem, str]], today: str) -> None:
    if not removed:
        return
    relpath = f"{_ARCHIVE_DIR}/{filename}"
    existing = await vault_read(relpath)
    content = "" if existing.get("error") else existing.get("content", "")
    if not content.strip():
        content = f"---\nlast_updated: {today}\n---\n\n# Archived ({filename})\n"
    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    block = [f"\n## Compacted {stamp}\n"]
    for it, reason in removed:
        block.append(f"- _({reason})_ " + _make_bullet(it)[2:])
    await vault_write(relpath, content.rstrip() + "\n" + "\n".join(block) + "\n")


# ── Public interface ─────────────────────────────────────────────────────────

async def compact_all() -> dict:
    """Distil every memory kind-note. Reversible (removed bullets are archived).

    Returns a summary: per-file kept/archived counts + reason tally. Never raises.
    """
    today = time.strftime("%Y-%m-%d", time.gmtime())
    files: dict[str, dict] = {}
    totals = {"kept": 0, "archived": 0, "noise": 0, "aged": 0, "superseded": 0, "similar": 0}

    for filename, kind in _FILE_TO_KIND.items():
        relpath = f"{_MEMORY_BASE}/{filename}"
        read = await vault_read(relpath)
        if read.get("error"):
            continue
        items = _parse_note(read.get("content", ""), kind)
        if not items:
            continue
        survivors, archived = _compact_items(items)

        # Only rewrite when something actually changed.
        if archived:
            await _archive(filename, archived, today)
            await vault_write(relpath, _rebuild_note(kind, survivors, today))

        reasons: dict[str, int] = {}
        for _, reason in archived:
            reasons[reason] = reasons.get(reason, 0) + 1
            totals[reason] = totals.get(reason, 0) + 1
        totals["kept"] += len(survivors)
        totals["archived"] += len(archived)
        files[filename] = {"before": len(items), "kept": len(survivors),
                           "archived": len(archived), "reasons": reasons}

    await _write_index(files, today)
    return {"ok": True, "ts": today, "files": files, "totals": totals}


async def _write_index(files: dict[str, dict], today: str) -> None:
    """Regenerate the memory map-of-content so the spine is navigable."""
    lines = [
        f"---\nlast_updated: {today}\n---\n",
        "# Memory — Index\n",
        "Map of the distilled memory spine. Regenerated by the nightly compaction pass.",
        "The raw, append-only journal lives in `log/` and is never compacted.\n",
        "## Notes\n",
    ]
    for filename in _FILE_TO_KIND:
        kept = files.get(filename, {}).get("kept")
        suffix = f" — {kept} items" if kept is not None else ""
        lines.append(f"- [[{filename[:-3]}]]{suffix}")
    lines.append("\n## Last compaction\n")
    for filename, stats in files.items():
        if stats.get("archived"):
            lines.append(
                f"- **{filename}**: {stats['before']} → {stats['kept']} "
                f"(archived {stats['archived']}: {stats['reasons']})"
            )
    await vault_write(_INDEX_PATH, "\n".join(lines) + "\n")
