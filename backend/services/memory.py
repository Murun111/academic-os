"""Memory consolidation engine — Module C of Phase 1.1.

Orchestrates extraction → dedup → index → vault-write for a single thread.

Public interface:
    MEMORY_BACKEND  env var (default "ollama")
    MEMORY_MODEL    env var (default ""; means backend default)
    MAX_TURNS       int (12)
    extract_items(thread)           -> list[MemoryItem]
    consolidate_thread(thread)      -> ConsolidationResult
    consolidate_thread_id(tid)      -> ConsolidationResult

See: docs/specs/phase-1.1-memory-consolidation.md §Module C
"""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone

from backend.llm_hub import ChatMessage, get_backend
from backend.llm_hub import get_thread as _llm_get_thread
from backend.services.memory_index import find_similar, init_db, upsert_item
from backend.services.memory_types import MEMORY_KINDS, ConsolidationResult, MemoryItem
from backend.services.memory_writer import file_item, normalize_tag

log = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────

# LOCAL-first: default to the on-device Ollama backend, never a cloud backend.
MEMORY_BACKEND: str = os.environ.get("MEMORY_BACKEND", "ollama")
# The llm_hub Ollama backend REQUIRES an explicit model (it raises
# "ollama: model is required" on an empty string), so default to the same local
# model the rest of the OS uses. A small/fast model is fine — extraction only
# needs JSON output, not tool calls or deep reasoning.
MEMORY_MODEL: str = (
    os.environ.get("MEMORY_MODEL")
    or os.environ.get("OLLAMA_DEFAULT_MODEL")
    or "gemma4:latest"
)
MAX_TURNS: int = 12

# ── Extraction prompt (kept short for token economy) ──────────────────────────

_SYSTEM_PROMPT = (
    "You are a memory extraction assistant. "
    "Extract ONLY durable, reusable knowledge from the conversation below.\n\n"
    "A durable item is true and useful BEYOND this single exchange — a stable "
    "fact, a real decision and its reason, a genuine commitment, a lasting "
    "preference, a person/project/tool worth tracking, or a meaningful event.\n\n"
    "Do NOT extract (these are noise — skip them entirely):\n"
    "- the assistant's own behavior, greetings, acknowledgements, or echoes "
    '("responded with hello", "said done")\n'
    '- transient status that is only true right now ("inbox is empty", '
    '"3 open items", "currently gated / awaiting approval", "service is down")\n'
    "- test phrases, mandated exact responses, or one-off conversational scaffolding\n"
    "- anything you are not confident is durable — when in doubt, omit it\n\n"
    "Return ONLY a JSON array. "
    "Each element: "
    '{"kind": <one of fact|decision|todo|preference|entity|event>, '
    '"subject": "<short title>", '
    '"body": "<1–3 sentence durable statement>", '
    '"tags": ["<lowercase-keyword>"], '
    '"confidence": <0.0–1.0>}\n\n'
    "Prefer 0 items over noisy items. "
    "No prose, no markdown fences, no explanation — only the JSON array."
)

_MAX_MSG_CHARS = 800   # per-message cap to limit prompt tokens

# Items below this confidence are dropped at capture — too speculative to persist.
_MIN_CONFIDENCE = float(os.environ.get("MEMORY_MIN_CONFIDENCE", "0.35"))
# Bodies shorter than this can't carry a durable statement ("done", "ok").
_MIN_BODY_CHARS = 12

# Phrases that mark a candidate as ephemeral conversational exhaust rather than
# durable memory. Matched as substrings against "subject :: body" (lowercased).
# Tunable — this is the code-level backstop behind the prompt-level filter.
_META_MARKERS: tuple[str, ...] = (
    "the assistant", "assistant respond", "responded with", "echo",
    "greeting", "acknowledg", "user requested", "never mind",
    "confirms task", "task completion", "confirmation response",
    "initial response", "standard initial greeting",
)
_TRANSIENT_MARKERS: tuple[str, ...] = (
    "currently gated", "is gated", "gated state", "awaiting approval",
    "awaiting final approval", "awaiting necessary", "currently down",
    "currently non-operational", "service is currently", "is currently empty",
    "inbox is currently empty", "pending as of", "open item", "open items",
    "outstanding or active items", "three outstanding",
)
_FIXTURE_MARKERS: tuple[str, ...] = (
    "hermes online via hub", "echoes the context", "required response phrase",
    "mandated exact response", "must be used when following",
)


def is_noise(subject: str, body: str, confidence: float = 1.0) -> bool:
    """True if this candidate is ephemeral noise that should NOT be persisted.

    Backstop behind the prompt-level filter (the local model still leaks the
    obvious cases). Used both at capture (extract_items) and retroactively by
    the compaction pass to evict noise already in the spine. Conservative by
    design — it targets named ephemeral patterns, not broad keywords, so real
    facts that merely contain a word like "status" survive.
    """
    b = (body or "").strip()
    if confidence < _MIN_CONFIDENCE or len(b) < _MIN_BODY_CHARS:
        return True
    text = f"{(subject or '').strip().lower()} :: {b.lower()}"
    return any(
        marker in text
        for group in (_META_MARKERS, _TRANSIENT_MARKERS, _FIXTURE_MARKERS)
        for marker in group
    )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _build_conversation_text(messages: list[dict]) -> str:
    """Serialize the last MAX_TURNS messages into compact plain text."""
    tail = messages[-MAX_TURNS:]
    parts: list[str] = []
    for msg in tail:
        role = str(msg.get("role", "unknown")).upper()
        content = str(msg.get("content", ""))
        if len(content) > _MAX_MSG_CHARS:
            content = content[:_MAX_MSG_CHARS] + "…"
        parts.append(f"{role}: {content}")
    return "\n\n".join(parts)


def _parse_llm_response(raw: str) -> list[dict]:
    """Robustly extract a JSON array from the LLM response.

    Handles:
    - clean bare JSON array
    - array wrapped in ```json … ``` fences
    - array embedded in surrounding prose
    Returns [] on any parse failure.
    """
    # Strip markdown code fences (```json or ```)
    text = re.sub(r"```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
    text = re.sub(r"```\s*", "", text)

    # Find the outermost JSON array: first '[' to last ']'
    start = text.find("[")
    end = text.rfind("]")
    if start == -1 or end == -1 or end <= start:
        return []

    try:
        result = json.loads(text[start : end + 1])
        if isinstance(result, list):
            return result
    except json.JSONDecodeError:
        pass
    return []


def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ── Public interface ──────────────────────────────────────────────────────────

async def extract_items(thread: dict) -> list[MemoryItem]:
    """Call the cheap local LLM to distil MemoryItems from *thread*.

    Returns [] when the thread has no messages, the LLM call fails, or the
    response cannot be parsed.
    """
    messages = thread.get("messages", [])
    if not messages:
        return []

    conversation_text = _build_conversation_text(messages)

    try:
        backend = get_backend(MEMORY_BACKEND)
        result = await backend.chat(
            [
                ChatMessage("system", _SYSTEM_PROMPT),
                ChatMessage("user", conversation_text),
            ],
            model=MEMORY_MODEL,
        )
    except Exception as exc:
        log.warning("extract_items: LLM call failed (%s): %s", type(exc).__name__, exc)
        return []

    raw_objects = _parse_llm_response(result.content)

    thread_id = str(thread.get("id", ""))
    now_ts = _now_utc()
    items: list[MemoryItem] = []

    for obj in raw_objects:
        if not isinstance(obj, dict):
            continue

        kind = str(obj.get("kind", "")).strip()
        if kind not in MEMORY_KINDS:
            continue

        body = str(obj.get("body", "")).strip()
        if not body:
            continue

        subject = str(obj.get("subject", "")).strip()
        raw_tags = obj.get("tags", [])
        tags = (
            [nt for t in raw_tags if (nt := normalize_tag(str(t)))]
            if isinstance(raw_tags, list) else []
        )

        try:
            confidence = float(obj.get("confidence", 1.0))
        except (TypeError, ValueError):
            confidence = 1.0
        confidence = max(0.0, min(1.0, confidence))

        # Code-level backstop behind the prompt filter — drop ephemeral noise
        # before it ever reaches the index or the vault.
        if is_noise(subject, body, confidence):
            continue

        items.append(MemoryItem(
            kind=kind,
            subject=subject,
            body=body,
            tags=tags,
            source_thread=thread_id,
            ts=now_ts,
            confidence=confidence,
        ))

    return items


async def consolidate_thread(thread: dict) -> ConsolidationResult:
    """Extract, dedup, index, and file memory from *thread*.

    Never raises — wraps all errors in ConsolidationResult.error.
    """
    thread_id = str(thread.get("id", ""))
    try:
        items = await extract_items(thread)
        init_db()

        filed_items: list[MemoryItem] = []
        written_paths: list[str] = []
        seen_paths: set[str] = set()
        skipped_duplicates = 0

        for item in items:
            dup = find_similar(item)
            if dup is not None:
                skipped_duplicates += 1
                continue

            upsert_item(item)
            path = await file_item(item)
            filed_items.append(item)
            if path not in seen_paths:
                seen_paths.add(path)
                written_paths.append(path)

        return ConsolidationResult(
            thread_id=thread_id,
            items=filed_items,
            written_paths=written_paths,
            skipped_duplicates=skipped_duplicates,
            error="",
        )

    except Exception as exc:
        log.error("consolidate_thread(%r) failed: %s: %s", thread_id, type(exc).__name__, exc)
        return ConsolidationResult(
            thread_id=thread_id,
            error=f"{type(exc).__name__}: {exc}",
        )


async def consolidate_thread_id(tid: str) -> ConsolidationResult:
    """Fetch thread by *tid* from llm_hub and consolidate it.

    Returns ConsolidationResult(error="thread_not_found") when *tid* is unknown.
    """
    thread = _llm_get_thread(tid)
    if thread is None:
        return ConsolidationResult(thread_id=tid, error="thread_not_found")
    return await consolidate_thread(thread)
