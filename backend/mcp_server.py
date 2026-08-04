"""Agentic OS — MCP server (stdio).

Exposes the OS's high-value tools to any MCP client (Antigravity/Gemini,
Claude Code, Cursor, …). This is how you "use Gemini with the OS": you chat
with Gemini inside Antigravity, and Gemini drives the OS through these tools.

Architecture: a THIN PROXY. Every tool just calls the already-running OS REST
API at AGENTIC_OS_URL (default http://127.0.0.1:7878, started by the
LaunchAgent). No duplicated state, no second memory index — one OS instance,
many front doors. Outward/risky actions still pass through the OS's own
autonomy gate server-side, so a model cannot move money or send things without
your approval.

Run (Antigravity launches it for you via mcp_config.json):
    python backend/mcp_server.py

Wire into Antigravity: add to ~/.gemini/antigravity/mcp_config.json under
"mcpServers" (see scripts/install_mcp.py).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Allow running as a bare script (Antigravity launches it by absolute path).
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import httpx  # noqa: E402
from mcp.server.fastmcp import FastMCP  # noqa: E402

BASE_URL = os.environ.get("AGENTIC_OS_URL", "http://127.0.0.1:7878").rstrip("/")

mcp = FastMCP("agentic-os")


async def _get(path: str, params: dict | None = None, timeout: float = 30.0) -> dict:
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.get(f"{BASE_URL}{path}", params=params)
            return _unwrap(r)
    except httpx.HTTPError as e:
        return {"error": f"OS unreachable at {BASE_URL} ({type(e).__name__}). Is the Agentic OS server running?"}


async def _post(path: str, body: dict | None = None, timeout: float = 30.0) -> dict:
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.post(f"{BASE_URL}{path}", json=body or {})
            return _unwrap(r)
    except httpx.HTTPError as e:
        return {"error": f"OS unreachable at {BASE_URL} ({type(e).__name__}). Is the Agentic OS server running?"}


def _unwrap(r: httpx.Response) -> dict:
    try:
        data = r.json()
    except Exception:
        return {"error": f"non-JSON response ({r.status_code})", "body": r.text[:500]}
    if isinstance(data, dict):
        return data
    return {"result": data}


# ── Reasoning ────────────────────────────────────────────────────────────────

@mcp.tool()
async def consensus_ask(question: str, panel: list[str] | None = None,
                        mode: str = "synthesize") -> dict:
    """Get a multi-model second opinion on a hard decision. Asks a panel of
    different model families (claude, codex, gemini by default) the same
    question, then synthesizes their stances. mode="council" adds a
    cross-review round — every panelist scores the anonymized answers and the
    best response wins (~2x the calls). Use for genuine go/no-go or
    'X vs Y' calls where one model's blind spot is a real risk."""
    return await _post("/api/consensus",
                       {"question": question, "panel": panel, "mode": mode},
                       timeout=420.0)


# ── Memory spine ─────────────────────────────────────────────────────────────

@mcp.tool()
async def memory_search(query: str, k: int = 8) -> dict:
    """Search the OS's long-term memory spine (facts, decisions, todos,
    preferences, entities, events distilled from past conversations)."""
    return await _get("/api/memory/search", {"q": query, "k": k})


@mcp.tool()
async def memory_compact() -> dict:
    """Distil the memory spine: merge duplicates, supersede stale facts, evict
    noise, age out old items. Reversible — removed items are archived."""
    return await _post("/api/memory/compact", timeout=180.0)


# ── C-Suite agents ───────────────────────────────────────────────────────────

@mcp.tool()
async def agents_list() -> dict:
    """List the OS's agents (CEO/CFO/CTO/CMO/COO, etc.) with their schedules
    and status."""
    return await _get("/api/agents")


@mcp.tool()
async def agent_run(name: str) -> dict:
    """Run a named agent now (e.g. 'coo', 'ceo', 'self-improve'). Returns the
    run record; the agent executes in the background under the autonomy gate."""
    return await _post(f"/api/agents/{name}/run")


@mcp.tool()
async def cos_goal(goal: str) -> dict:
    """Hand a natural-language goal to the Chief of Staff. It decomposes the
    goal, delegates to the relevant domain agents, synthesizes, and files the
    result. Returns immediately (runs in background)."""
    return await _post("/api/cos/goal", {"goal": goal})


# ── Life tools (read + low-risk add; outward actions stay gated server-side) ──

@mcp.tool()
async def calendar_events(start: str, end: str) -> dict:
    """List calendar events in [start, end) (ISO-8601 datetimes)."""
    return await _get("/api/calendar/events", {"start": start, "end": end})


@mcp.tool()
async def money_summary() -> dict:
    """Money health: net worth, by-category breakdown, 30-day cashflow."""
    return await _get("/api/money/summary")


@mcp.tool()
async def inbox_list(status: str | None = None) -> dict:
    """List inbox items, optionally filtered by status (open | done | snoozed)."""
    return await _get("/api/inbox/items", {"status": status} if status else None)


@mcp.tool()
async def inbox_add(text: str, priority: str = "normal", due: str | None = None) -> dict:
    """Add an item to the inbox. priority: low|normal|high; due: YYYY-MM-DD."""
    body = {"text": text, "priority": priority}
    if due:
        body["due"] = due
    return await _post("/api/inbox/items", body)


# ── Knowledge base ───────────────────────────────────────────────────────────

@mcp.tool()
async def wiki_search(q: str, limit: int = 20) -> dict:
    """Full-text search across the Obsidian vault (wiki, notes, output)."""
    return await _get("/api/wiki/search", {"q": q, "limit": limit})


# ── Translator (Phase C — English↔Mongolian, Translation Memory) ──────────────

@mcp.tool()
async def translate(text: str, direction: str = "en-mn", use_kb: bool = True) -> dict:
    """Translate between English and Mongolian, conditioned on the OS's Translation
    Memory (your past pairs + corrections) and the vault grammar KB. direction:
    'en-mn' (English→Mongolian) or 'mn-en'. Writes an editable review file under
    wiki/_translations/ that you can correct, then feed back via translation_capture."""
    return await _post("/api/translate",
                       {"text": text, "direction": direction, "use_kb": use_kb},
                       timeout=180.0)


@mcp.tool()
async def translation_add_pair(english: str, mongolian: str, direction: str = "both") -> dict:
    """Add an English↔Mongolian sentence pair to the Translation Memory, growing
    the private corpus future translations retrieve as few-shot. direction:
    'en-mn' | 'mn-en' | 'both'."""
    return await _post("/api/translate/pairs",
                       {"en": english, "mn": mongolian, "direction": direction})


@mcp.tool()
async def translation_capture(review_file: str) -> dict:
    """Capture your correction from a translation review file (a
    wiki/_translations/*.md path) into the Translation Memory, so the translator
    learns from it. Returns how many corrections were captured (0 or 1)."""
    return await _post("/api/translate/capture", {"review_file": review_file})


@mcp.tool()
async def translate_auto_cycle(sources: list[str] | None = None,
                               direction: str = "en-mn",
                               threshold: float = 0.5,
                               best_of: int = 3) -> dict:
    """Run the autonomous self-improving translation cycle: for each task generate
    `best_of` candidates and keep the best by the reward (back-translation chrF +
    critic), auto-capture confident pairs into the Translation Memory, and flag the
    rest for review. With no `sources`, drains the vault queue file
    (raw/_translate_queue.md). Returns {processed, captured, flagged, avg_chrf}."""
    return await _post("/api/translate/auto",
                       {"sources": sources, "direction": direction,
                        "threshold": threshold, "best_of": best_of},
                       timeout=900.0)


@mcp.tool()
async def translate_voice(audio_path: str, direction: str = "mn-en",
                          language: str | None = None) -> dict:
    """Transcribe a local audio file with local Whisper and translate it —
    'talk to it in Mongolian'. `audio_path` is a path on the OS host. direction:
    'mn-en' (Mongolian speech → English) or 'en-mn'. Returns transcription +
    translation; reports an install hint if no speech-to-text backend is present."""
    return await _post("/api/translate/voice",
                       {"audio_path": audio_path, "direction": direction,
                        "language": language}, timeout=300.0)


@mcp.tool()
async def translate_murmur_latest(direction: str = "en-mn") -> dict:
    """Translate the latest dictation from Murmur (the local macOS dictation app):
    'talk to it' by dictating with Murmur, then translate what you said. Murmur's
    speech-to-text is English-tuned, so direction defaults to en-mn (speak English
    → Mongolian). Returns transcription + translation."""
    return await _post("/api/translate/murmur", {"direction": direction}, timeout=300.0)


if __name__ == "__main__":
    mcp.run()
