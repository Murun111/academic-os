"""Memory writer — Module B of Phase 1.1 Memory Consolidation.

Files MemoryItems as markdown into the Obsidian vault under
``Agentic OS/memory/``.  One note per kind plus a daily chronological
log under ``Agentic OS/memory/log/<YYYY-MM-DD>.md``.

Public interface (matches the spec contract exactly):

    route(item)         -> vault relpath
    file_item(item)     -> coroutine → relpath
    file_items(items)   -> coroutine → list[relpath]  (de-duplicated)

See: docs/specs/phase-1.1-memory-consolidation.md §Module B
"""
from __future__ import annotations

import logging
import re
import time

from backend.services.memory_types import MemoryItem
from backend.services.tools import vault_read, vault_write

log = logging.getLogger(__name__)

# ── Path constants ──────────────────────────────────────────────────────────

_MEMORY_BASE = "Agentic OS/memory"

_KIND_TO_FILE: dict[str, str] = {
    "fact":       f"{_MEMORY_BASE}/facts.md",
    "decision":   f"{_MEMORY_BASE}/decisions.md",
    "todo":       f"{_MEMORY_BASE}/todos.md",
    "preference": f"{_MEMORY_BASE}/preferences.md",
    "entity":     f"{_MEMORY_BASE}/entities.md",
    "event":      f"{_MEMORY_BASE}/events.md",
}

_MISC = f"{_MEMORY_BASE}/misc.md"


# ── Public interface ────────────────────────────────────────────────────────

def normalize_tag(tag: str) -> str:
    """Canonicalize a tag so the Obsidian tag index stays clean.

    Lowercases, strips a leading '#', and collapses spaces/punctuation to single
    hyphens (Obsidian tags can't contain spaces). Returns "" for empty/garbage
    input so callers can filter it out. Examples:
        "#Finance" -> "finance"   "daily life" -> "daily-life"   "  " -> ""
    """
    t = tag.strip().lstrip("#").lower()
    t = re.sub(r"[^\w/-]+", "-", t)   # spaces & punctuation → hyphen
    t = re.sub(r"-{2,}", "-", t).strip("-/")
    return t


def route(item: MemoryItem) -> str:
    """Return the vault relpath for *item* based on its kind.

    Unknown kinds map to ``Agentic OS/memory/misc.md``.
    """
    return _KIND_TO_FILE.get(item.kind, _MISC)


async def file_item(item: MemoryItem) -> str:
    """Write *item* into its kind-note and the daily log.

    Steps:
    1. Resolve destination relpath via ``route()``.
    2. Read existing note (or create fresh) via ``vault_read``.
    3. Ensure YAML frontmatter exists; bump ``last_updated`` to today (UTC).
    4. Append the bullet **unless** ``item.body`` already appears in the note
       (cheap idempotency — no dup even if re-filed).
    5. Write the kind-note via ``vault_write``.
    6. Repeat steps 2–5 for the daily log at
       ``Agentic OS/memory/log/<YYYY-MM-DD>.md``.
    7. Set ``item.vault_path`` to the kind-note relpath.
    8. Return the kind-note relpath.

    Errors from ``vault_write`` (returned as ``{"error": ...}`` dicts) are
    logged as warnings; this function does not raise.
    """
    today = _today_utc()
    relpath = route(item)
    bullet = _make_bullet(item)

    await _append_to_note(
        relpath=relpath,
        bullet=bullet,
        body=item.body,
        today=today,
        heading=item.kind.capitalize(),
    )
    item.vault_path = relpath

    log_relpath = f"{_MEMORY_BASE}/log/{today}.md"
    await _append_to_note(
        relpath=log_relpath,
        bullet=bullet,
        body=item.body,
        today=today,
        heading=f"Memory Log {today}",
    )

    return relpath


async def file_items(items: list[MemoryItem]) -> list[str]:
    """File each item and return the de-duplicated list of relpaths touched.

    The returned list includes both the per-kind note paths and the daily
    log path (at most one, since all items filed in the same UTC day share
    a single log note).
    """
    today = _today_utc()
    log_relpath = f"{_MEMORY_BASE}/log/{today}.md"

    seen: set[str] = set()
    touched: list[str] = []

    for item in items:
        relpath = await file_item(item)
        for p in (relpath, log_relpath):
            if p not in seen:
                seen.add(p)
                touched.append(p)

    return touched


# ── Internal helpers ────────────────────────────────────────────────────────

def _today_utc() -> str:
    return time.strftime("%Y-%m-%d", time.gmtime())


def _make_bullet(item: MemoryItem) -> str:
    """Format one MemoryItem as a Markdown bullet string."""
    base = (
        f"- [{item.ts}] **{item.subject}** — {item.body}"
        f"  ^thread-{item.source_thread}"
    )
    clean = [nt for t in item.tags if (nt := normalize_tag(t))]
    if clean:
        base += " " + " ".join(f"#{t}" for t in clean)
    return base


def _make_fresh_note(heading: str, today: str) -> str:
    """Return the initial content for a brand-new note."""
    return f"---\nlast_updated: {today}\n---\n\n# {heading}\n"


def _bump_frontmatter(content: str, today: str) -> str:
    """Ensure YAML frontmatter exists and set last_updated to *today*.

    Handles four cases:
    - Has frontmatter with ``last_updated`` line → update the value.
    - Has frontmatter without ``last_updated`` → append the key inside the block.
    - Has malformed frontmatter (no closing ``---``) → prepend a fresh block.
    - Has no frontmatter at all → prepend a fresh block.
    """
    stripped = content.lstrip()
    if not stripped.startswith("---"):
        return f"---\nlast_updated: {today}\n---\n\n{content}"

    lines = content.split("\n")
    # Find the closing delimiter (first "---" after the opening one)
    close_idx: int | None = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            close_idx = i
            break

    if close_idx is None:
        # Malformed — prepend fresh block
        return f"---\nlast_updated: {today}\n---\n\n{content}"

    fm_lines = lines[1:close_idx]
    updated = False
    for i, line in enumerate(fm_lines):
        if line.strip().startswith("last_updated:"):
            fm_lines[i] = f"last_updated: {today}"
            updated = True
            break

    if not updated:
        fm_lines.append(f"last_updated: {today}")

    rebuilt = ["---"] + fm_lines + lines[close_idx:]
    return "\n".join(rebuilt)


async def _append_to_note(
    relpath: str,
    bullet: str,
    body: str,
    today: str,
    heading: str,
) -> None:
    """Core write routine shared by kind-notes and daily log.

    Always writes back (so ``last_updated`` is bumped even on re-file).
    Skips appending the bullet when *body* is already present in the note.
    """
    read_result = await vault_read(relpath)
    if "error" in read_result:
        content = _make_fresh_note(heading, today)
    else:
        content = _bump_frontmatter(read_result["content"], today)

    # Idempotency: only append when the exact body is not already there
    if body not in content:
        if not content.endswith("\n"):
            content += "\n"
        content += bullet + "\n"

    write_result = await vault_write(relpath, content)
    if "error" in write_result:
        log.warning(
            "vault_write failed for %r: %s", relpath, write_result.get("error")
        )
