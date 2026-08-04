"""Memory recall injection for Phase 1.4.

Retrieves the most relevant memory items for a query and formats them into a
compact, token-bounded context block ready to inject into an LLM prompt.

No network calls — retrieval is fully delegated to memory_index.search().
"""
from __future__ import annotations

import os

from backend.services import memory_index

RECALL_K: int = int(os.environ.get("MEMORY_RECALL_K", "6"))
RECALL_MAX_CHARS: int = int(os.environ.get("MEMORY_RECALL_MAX_CHARS", "1200"))

_HEADER = (
    "[Memory — relevant context about the user."
    " Use if helpful; do not mention unless asked.]"
)


def format_context(items: list) -> str:
    """Format a list of MemoryItems into a compact context block.

    Returns '' for an empty list. Otherwise returns the header line followed by
    one bullet per item: ``- (<kind>) <subject> — <body>``.
    """
    if not items:
        return ""
    lines = [_HEADER]
    for item in items:
        lines.append(f"- ({item.kind}) {item.subject} — {item.body}")
    return "\n".join(lines)


def recall(
    query: str,
    k: int = RECALL_K,
    max_chars: int = RECALL_MAX_CHARS,
) -> str:
    """Return a compact, ready-to-inject context block, or '' if nothing relevant.

    Calls memory_index.search(query, k), formats the results with
    format_context(), then truncates to max_chars on item (line) boundaries —
    whole bullets are dropped rather than split mid-line; the header is always
    retained when it fits.  Never raises — returns '' on any error.
    """
    try:
        if not query or not query.strip():
            return ""

        items = memory_index.search(query, k)
        if not items:
            return ""

        full = format_context(items)
        if len(full) <= max_chars:
            return full

        # Truncate on whole-line boundaries: keep the header, greedily add bullets.
        lines = full.split("\n")
        header = lines[0]

        if len(header) > max_chars:
            # Header alone already exceeds budget — nothing safe to return.
            return ""

        kept = [header]
        for line in lines[1:]:
            candidate = "\n".join(kept + [line])
            if len(candidate) <= max_chars:
                kept.append(line)
            else:
                break  # remaining bullets won't fit either (they're similar length)

        return "\n".join(kept)

    except Exception:  # noqa: BLE001
        return ""
