"""Tool registry for the agent runner.

An agent prompt can ask for capabilities by name; the registry
resolves them to callables that the agent runner invokes. The
callable gets a small dict of arguments (from the model) and
returns a JSON-serializable result.

Adding a new tool = add a ToolSpec to TOOLS. No new wiring needed.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from backend.services.calendar import AppleCalendarService
from backend.services.inbox import InboxService
from backend.services.browser import BrowserService
from backend.vault import resolve_vault_path  # re-exported for tests


@dataclass
class ToolSpec:
    """Description of one tool the agent runner can call."""

    name: str
    description: str  # shown to the model so it knows when to call
    parameters: dict  # JSON Schema for the args
    handler: Callable[..., Awaitable[Any]]  # the actual implementation


# === Tool implementations ===

# Each handler is `async def tool_xxx(...) -> dict`. They take the
# relevant service as a parameter so tests can pass mocks.

async def calendar_list_events(
    calendar_service: AppleCalendarService,
    start: str,
    end: str,
) -> dict:
    """List events in [start, end) ISO-8601 range."""
    from datetime import datetime
    s = datetime.fromisoformat(start)
    e = datetime.fromisoformat(end)
    events = calendar_service.list_events(start=s, end=e)
    return {"events": [ev.to_dict() for ev in events], "count": len(events)}


async def inbox_list_open(inbox_service: InboxService) -> dict:
    """List open inbox items."""
    items = inbox_service.list_all(status="open")
    return {"items": [i.to_dict() for i in items], "count": len(items)}


async def inbox_add(
    inbox_service: InboxService,
    text: str,
    priority: str = "normal",
    due: str | None = None,
) -> dict:
    """Add a new inbox item."""
    from datetime import date
    due_date = date.fromisoformat(due) if due else None
    item = inbox_service.add(text=text, priority=priority, due=due_date)
    return item.to_dict()


async def inbox_mark_done(inbox_service: InboxService, item_id: str) -> dict:
    """Mark an inbox item as done."""
    item = inbox_service.mark_done(item_id)
    return item.to_dict()


async def browser_search(
    browser_service: BrowserService, query: str, macro: str = "@google_search",
) -> dict:
    """Search the web via a search macro (default: Google)."""
    return await browser_service.research_search(query=query, macro=macro)


async def browser_fetch(browser_service: BrowserService, url: str) -> dict:
    """Fetch a URL and return its text + outbound links."""
    return await browser_service.research_fetch(url=url)


async def web_search(query: str, limit: int = 8) -> dict:
    """Search the web via DuckDuckGo (plain HTTP, no daemon needed)."""
    from backend.services.websearch import search
    return await search(query, limit=limit)


async def web_fetch(url: str) -> dict:
    """Fetch a URL and return its readable text (plain HTTP)."""
    from backend.services.websearch import fetch
    return await fetch(url)


async def academics_upcoming_deadlines(days: int = 14) -> dict:
    """Merged application + assignment deadlines."""
    from backend.services.academics_tools import upcoming_deadlines
    return await upcoming_deadlines(days=days)


async def academics_student_profile() -> dict:
    """Stage/track/exam-date for tailoring searches (never the student's name)."""
    from backend.services.academics_tools import student_profile
    return await student_profile()


async def academics_add_application(name: str, type: str = "scholarship",
                                    deadline: str | None = None, org: str = "",
                                    url: str = "", notes: str = "") -> dict:
    """GATED: create a card in the Applications pipeline."""
    from backend.services.academics_tools import add_application
    return await add_application(name=name, type=type, deadline=deadline,
                                 org=org, url=url, notes=notes)


async def vault_read(path: str) -> dict:
    """Read a file from the vault. Path is relative to the vault root.

    Refuses to read outside the vault root (path traversal).
    Refuses to read credential files under data/connectors/.
    """
    from pathlib import Path
    from backend.vault import resolve_vault_path
    full = (resolve_vault_path() / path).resolve()
    vault_root = resolve_vault_path().resolve()
    if not str(full).startswith(str(vault_root)):
        return {"error": "path_escape", "path": path}
    # Disallow credential files (per CLAUDE.md)
    connectors_dir = (vault_root / "data" / "connectors").resolve()
    if str(full).startswith(str(connectors_dir)):
        return {"error": "forbidden", "path": path,
                "detail": "credential files are not readable by agents"}
    if not full.exists():
        return {"error": "not_found", "path": path}
    return {"path": path, "content": full.read_text()}


async def reminders_create(title: str, due: str | None = None, notes: str | None = None) -> dict:
    """Create a reminder in Apple Reminders.app."""
    from backend.services.reminders import create_reminder
    return await create_reminder(title, due, notes)


async def _set_schedule(agent: str, schedule: str | None = None, enabled: bool | None = None) -> dict:
    """Thin wrapper — lazy-imports agent_admin to avoid circular deps at module load."""
    from backend.services.agent_admin import set_schedule
    return await set_schedule(agent, schedule, enabled)


async def _autonomy_allow(tool: str) -> dict:
    """Thin wrapper — lazy-imports agent_admin to avoid circular deps at module load."""
    from backend.services.agent_admin import autonomy_allow
    return await autonomy_allow(tool)


async def system_audit() -> dict:
    """Read-only self-audit: returns observations about agent runs, failures, etc."""
    from backend.services.self_audit import audit
    return audit()


async def memory_compact() -> dict:
    """Distil the memory spine: merge duplicates, supersede stale facts, evict
    noise, age out old items. Reversible — removed bullets are archived."""
    from backend.services.memory_compact import compact_all
    return await compact_all()


async def consensus_ask(question: str, panel: list | None = None,
                        mode: str = "synthesize") -> dict:
    """Get a multi-model second opinion: ask a panel of different model families
    the same question, then synthesize their stances. mode="council" adds a
    cross-review round where panelists score each other and the best answer wins."""
    from backend.services.consensus import consensus
    return await consensus(question, panel=panel, mode=mode)


async def _code_task(task: str, project: str, backend: str = "claude", mode: str = "solo") -> dict:
    """Thin wrapper — lazy-imports code_task to avoid circular deps at module load."""
    from backend.services.code_task import run_code_task
    return await run_code_task(task, project, backend, mode)


async def vault_write(path: str, content: str) -> dict:
    """Write a file to the vault. Path is relative to the vault root.

    Refuses to write outside the vault root (path traversal).
    Refuses to write to user-authored folders.
    """
    from pathlib import Path
    from backend.vault import resolve_vault_path
    full = (resolve_vault_path() / path).resolve()
    vault_root = resolve_vault_path().resolve()
    if not str(full).startswith(str(vault_root)):
        return {"error": "path_escape", "path": path}
    # Disallow user-authored folders (per CLAUDE.md)
    for blocked in ("aa) Murun", "Ascent Studios Co", "Parvis Ai", "Improvability"):
        if blocked in path:
            return {"error": "user_authored", "path": path}
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(content)
    return {"ok": True, "path": path, "bytes": len(content)}


# === Registry ===

def build_tools(
    calendar_service: AppleCalendarService | None = None,
    inbox_service: InboxService | None = None,
    browser_service: BrowserService | None = None,
) -> list[ToolSpec]:
    """Build the full tool list. Services can be None (those tools become no-ops).

    We accept None rather than failing hard so the runner can start
    in a degraded state (e.g. CalDAV creds missing → calendar tools unavailable
    but the rest still work).
    """
    tools: list[ToolSpec] = []

    # Web research — always available (plain HTTP, works on any machine).
    tools.append(ToolSpec(
        name="web.search",
        description="Search the web. Use for research: scholarships, programs, deadlines. Returns titles + URLs; follow up with web.fetch.",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "The search query"},
                "limit": {"type": "integer", "description": "max results (default 8)"},
            },
            "required": ["query"],
        },
        handler=lambda query, limit=8: web_search(query, limit=limit),
    ))
    tools.append(ToolSpec(
        name="web.fetch",
        description="Fetch a URL and return its readable text. Use after web.search to read a result page.",
        parameters={
            "type": "object",
            "properties": {"url": {"type": "string"}},
            "required": ["url"],
        },
        handler=lambda url: web_fetch(url),
    ))

    # Academic modules — always available.
    tools.append(ToolSpec(
        name="academics.upcoming_deadlines",
        description="Upcoming application deadlines and assignment due dates, merged and sorted. Use for 'what's due soon'.",
        parameters={
            "type": "object",
            "properties": {"days": {"type": "integer", "description": "window in days (default 14, max 90)"}},
        },
        handler=lambda days=14: academics_upcoming_deadlines(days=days),
    ))
    tools.append(ToolSpec(
        name="academics.student_profile",
        description=(
            "The student's stage (highschool/undergrad/gapyear/grad/beyond), post-undergrad "
            "track (premed/prelaw/predental/gradschool), and exam date. Use to tailor searches."
        ),
        parameters={"type": "object", "properties": {}},
        handler=lambda: academics_student_profile(),
    ))
    tools.append(ToolSpec(
        name="academics.add_application",
        description=(
            "GATED WRITE: add an application/scholarship/program card to the student's "
            "pipeline (Researching column). Only propose entries you verified via "
            "web.fetch, with the official URL and deadline. Requires the student's approval."
        ),
        parameters={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "e.g. 'Gates Scholarship 2027'"},
                "type": {"type": "string", "enum": ["undergrad", "grad", "scholarship", "exchange"]},
                "deadline": {"type": "string", "description": "ISO date if known"},
                "org": {"type": "string", "description": "school or funder"},
                "url": {"type": "string", "description": "official page URL"},
                "notes": {"type": "string", "description": "amount, eligibility, why it fits"},
            },
            "required": ["name"],
        },
        handler=lambda name, type="scholarship", deadline=None, org="", url="", notes="":
            academics_add_application(name=name, type=type, deadline=deadline,
                                      org=org, url=url, notes=notes),
    ))

    if calendar_service is not None:
        tools.append(ToolSpec(
            name="calendar.list_events",
            description="List calendar events in a date range. Use this for 'what's on my calendar today/this week/this month'.",
            parameters={
                "type": "object",
                "properties": {
                    "start": {"type": "string", "description": "ISO 8601 datetime, inclusive"},
                    "end": {"type": "string", "description": "ISO 8601 datetime, exclusive"},
                },
                "required": ["start", "end"],
            },
            handler=lambda start, end: calendar_list_events(calendar_service, start, end),
        ))

    if inbox_service is not None:
        tools.append(ToolSpec(
            name="inbox.list_open",
            description="List all open inbox items (not yet done).",
            parameters={"type": "object", "properties": {}},
            handler=lambda: inbox_list_open(inbox_service),
        ))
        tools.append(ToolSpec(
            name="inbox.add",
            description="Add a new item to the inbox.",
            parameters={
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "Required. The thing to remember."},
                    "priority": {"type": "string", "enum": ["low", "normal", "high"]},
                    "due": {"type": "string", "description": "ISO 8601 date YYYY-MM-DD, optional"},
                },
                "required": ["text"],
            },
            handler=lambda text, priority="normal", due=None: inbox_add(
                inbox_service, text=text, priority=priority, due=due
            ),
        ))
        tools.append(ToolSpec(
            name="inbox.mark_done",
            description="Mark an inbox item as done (by its id).",
            parameters={
                "type": "object",
                "properties": {
                    "item_id": {"type": "string"},
                },
                "required": ["item_id"],
            },
            handler=lambda item_id: inbox_mark_done(inbox_service, item_id),
        ))

    if browser_service is not None:
        tools.append(ToolSpec(
            name="browser.search",
            description="Search the web via a search macro. Default is Google. Use this for any 'look up' or 'research' request.",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "The search query"},
                    "macro": {"type": "string", "default": "@google_search",
                              "description": "Search macro: @google_search, @wikipedia_search, etc."},
                },
                "required": ["query"],
            },
            handler=lambda query, macro="@google_search": browser_search(
                browser_service, query, macro),
        ))
        tools.append(ToolSpec(
            name="browser.fetch",
            description="Fetch a URL and return its text + outbound links. Use after browser.search to dig into a result.",
            parameters={
                "type": "object",
                "properties": {
                    "url": {"type": "string"},
                },
                "required": ["url"],
            },
            handler=lambda url: browser_fetch(browser_service, url),
        ))

    # loop.set_schedule — GATED: reschedule / enable / disable an agent spec
    tools.append(ToolSpec(
        name="loop.set_schedule",
        description=(
            "Reschedule, enable, or disable an agent by editing its spec. "
            "GATED: requires the user's approval. "
            "Args: agent (name), schedule (cron string, or empty to remove the schedule), "
            "enabled (true/false)."
        ),
        parameters={
            "type": "object",
            "properties": {
                "agent": {"type": "string"},
                "schedule": {"type": "string"},
                "enabled": {"type": "boolean"},
            },
            "required": ["agent"],
        },
        handler=lambda agent, schedule=None, enabled=None: _set_schedule(agent, schedule, enabled),
    ))

    # autonomy.allow — GATED: promote a tool to auto-allowed
    tools.append(ToolSpec(
        name="autonomy.allow",
        description=(
            "Promote a tool to auto-allowed (no longer gated). "
            "GATED: requires the user's approval. "
            "Args: tool (the tool name to auto-allow)."
        ),
        parameters={
            "type": "object",
            "properties": {
                "tool": {"type": "string"},
            },
            "required": ["tool"],
        },
        handler=lambda tool: _autonomy_allow(tool),
    ))

    # reminders tool — always available (no service dependency; osascript on macOS)
    tools.append(ToolSpec(
        name="reminders.create",
        description=(
            "Create a reminder in Apple Reminders for a time-sensitive to-do or deadline. "
            "GATED: requires the user's approval before it actually creates the reminder."
        ),
        parameters={
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "The reminder text"},
                "due": {"type": "string", "description": "Optional due date, YYYY-MM-DD"},
                "notes": {"type": "string", "description": "Optional notes/body"},
            },
            "required": ["title"],
        },
        handler=lambda title, due=None, notes=None: reminders_create(title, due, notes),
    ))

    # code.task — GATED: spawns a CLI coding agent that writes files to disk
    tools.append(ToolSpec(
        name="code.task",
        description=(
            "Delegate a real coding task to a CLI coding agent which writes the code "
            "into ~/Code/agentic-os-projects/<project>. "
            "GATED: requires the user's approval before any code is written. "
            "Args: task (a detailed spec of what to build), project (short folder name), "
            "backend (optional: claude|codex, default claude — used in solo mode), "
            "mode (optional: 'solo' = one agent builds; 'collab' = claude builds then "
            "codex reviews & fixes; 'panel' = claude builds → codex reviews → gemini "
            "reviews, a third pair of eyes. Use collab/panel for real/important builds)."
        ),
        parameters={
            "type": "object",
            "properties": {
                "task": {"type": "string", "description": "Detailed build spec"},
                "project": {"type": "string", "description": "Short project/folder name"},
                "backend": {"type": "string", "description": "claude or codex (solo mode, default claude)"},
                "mode": {"type": "string", "description": "solo (one agent) or collab (claude builds → codex reviews & fixes)"},
            },
            "required": ["task", "project"],
        },
        handler=lambda task, project, backend="claude", mode="solo": _code_task(task, project, backend, mode),
    ))

    # system.audit — always available, no service dependency, read-only
    tools.append(ToolSpec(
        name="system.audit",
        description=(
            "Read-only self-audit: returns observations about the OS's own agent runs, "
            "failures, gated actions, approval patterns, and scheduling — used to propose improvements."
        ),
        parameters={"type": "object", "properties": {}},
        handler=system_audit,
    ))

    # memory.compact — always available, internal-reversible (archives, never deletes)
    tools.append(ToolSpec(
        name="memory.compact",
        description=(
            "Distil the memory spine: merge duplicate facts, supersede stale ones, "
            "evict conversational noise, and age out old items. Removed items are "
            "archived (reversible), never deleted. Returns a per-file summary. "
            "Run this to keep long-term memory small and high-signal."
        ),
        parameters={"type": "object", "properties": {}},
        handler=memory_compact,
    ))

    # consensus.ask — always available, read-tier (reasoning aid, no side effects)
    tools.append(ToolSpec(
        name="consensus.ask",
        description=(
            "Get a multi-model second opinion on a hard question or decision. "
            "Asks a panel of different model families (claude, codex, gemini by "
            "default) the SAME question concurrently, then synthesizes their "
            "stances — where they agree, disagree, and a final recommendation. "
            "mode='council' adds a cross-review round: every panelist scores the "
            "anonymized answers and the best response wins (~2x the calls). "
            "Use for genuine go/no-go or 'X vs Y' decisions where one model's "
            "blind spot is a real risk. Offline backends drop out automatically."
        ),
        parameters={
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "The decision/question to put to the panel"},
                "panel": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional backend names to consult (default: claude, codex, gemini)",
                },
                "mode": {
                    "type": "string",
                    "enum": ["synthesize", "council"],
                    "description": "synthesize (default) = merge stances; council = cross-review + best response",
                },
            },
            "required": ["question"],
        },
        handler=lambda question, panel=None, mode="synthesize": consensus_ask(question, panel, mode),
    ))

    # vault tools are always available
    tools.append(ToolSpec(
        name="vault.read",
        description="Read a file from the vault. Path is relative to vault root (e.g. 'wiki/overview.md').",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
            },
            "required": ["path"],
        },
        handler=vault_read,
    ))
    tools.append(ToolSpec(
        name="vault.write",
        description="Write a file to the vault. Path is relative to vault root. Refuses user-authored folders.",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["path", "content"],
        },
        handler=vault_write,
    ))

    return tools


def tools_to_ollama_schema(tools: list[ToolSpec]) -> list[dict]:
    """Convert ToolSpecs to Ollama's tool-call schema format."""
    return [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description,
                "parameters": t.parameters,
            },
        }
        for t in tools
    ]


def get_tool_by_name(tools: list[ToolSpec], name: str) -> ToolSpec | None:
    for t in tools:
        if t.name == name:
            return t
    return None
