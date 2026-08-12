"""Agent routines — on-demand deadline watcher + essay feedback.

Two "routines" the user (or the scheduler, later) can trigger:

- deadline_digest / deadline_digest_llm: pulls upcoming application
  deadlines and assignment due dates from ApplicationsService and
  CoursesService into one merged list. Those two services are owned by
  other modules and may not exist yet (parallel build), so every call
  into them is wrapped in try/except — a missing or broken module just
  means that source is skipped, never a crash.
- essay_feedback: a single Ollama chat call with an admissions-essay
  coach system prompt. No storage — purely request/response.

Nothing here touches disk except lazily, through the foreign services'
own data directories under agentic_os_dir().
"""
from __future__ import annotations

from typing import Any, Optional

from backend.ollama import ChatMessage

_apps_service: Any | None = None
_courses_service: Any | None = None


def _get_applications_service() -> Any:
    """Lazy singleton for the (foreign) ApplicationsService.

    Import happens inside the function so this module can be imported
    even before backend/services/applications.py exists.
    """
    global _apps_service
    if _apps_service is None:
        from backend.services.applications import ApplicationsService
        from backend.vault import agentic_os_dir

        _apps_service = ApplicationsService(data_dir=agentic_os_dir() / "data" / "applications")
    return _apps_service


def _get_courses_service() -> Any:
    """Lazy singleton for the (foreign) CoursesService."""
    global _courses_service
    if _courses_service is None:
        from backend.services.courses import CoursesService
        from backend.vault import agentic_os_dir

        _courses_service = CoursesService(data_dir=agentic_os_dir() / "data" / "courses")
    return _courses_service


def reset_foreign_services() -> None:
    """Test hook — clear cached lazy singletons between tests."""
    global _apps_service, _courses_service
    _apps_service = None
    _courses_service = None


# Feedback criteria distilled from the Harvard College Writing Center's
# "Strategies for Essay Writing" (writingcenter.fas.harvard.edu), adapted to
# cover both academic essays and admissions/personal essays.
_ESSAY_COACH_SYSTEM = (
    "You are an essay coach for students. Review the essay against these "
    "criteria, in this order of importance:\n"
    "1. ANSWERS THE PROMPT — if a prompt is given, check the essay actually does "
    "what the prompt's action verbs ask (analyze/compare/argue ≠ summarize). "
    "The most common failure is summarizing when asked to argue.\n"
    "2. CENTRAL CLAIM / CENTRAL STORY — an academic essay needs one arguable "
    "thesis a thoughtful reader could disagree with (not a description). A "
    "personal/admissions essay needs the equivalent: one specific insight about "
    "the writer that the whole piece develops. Name what the essay's central "
    "claim or insight is; if you can't, that's the top problem.\n"
    "3. SO WHAT — does the essay explain why its question, story, or claim "
    "matters? Readers need stakes, not a dramatic hook.\n"
    "4. PARAGRAPHS — each paragraph should make ONE point, open with a sentence "
    "that advances the argument (not just describes), and interpret its "
    "evidence rather than assume it speaks for itself.\n"
    "5. FLOW — transitions should connect old information to new information; "
    "flag jumps where the connection between ideas lives only in the writer's "
    "head.\n"
    "6. COMPLICATION — strong essays engage the obvious objection or the "
    "messier version of their story instead of ignoring it.\n"
    "7. ENDING — the conclusion should say what the essay now means (the 'so "
    "what'), not restate the introduction. Flag endings that merely repeat.\n"
    "8. SPECIFICITY AND VOICE — flag cliches, borrowed phrases, and generic "
    "sentences any other student could have written; point to the most "
    "specific, alive sentence in the draft as the standard the rest should "
    "meet.\n"
    "Give numbered, actionable feedback the student can apply themselves, "
    "quoting short phrases from the essay as evidence. Lead with the most "
    "important problem, not the first one you noticed. Do not rewrite the "
    "essay wholesale — coach, don't replace."
)

_BRIEFING_SYSTEM = (
    "You are a calm, motivational academic assistant. Turn the deadline "
    "digest below into a short briefing (3-5 sentences) that helps the "
    "student prioritize without inducing panic."
)


async def essay_feedback(ollama: Any, text: str, prompt_hint: str = "") -> dict:
    """Run the essay through the admissions-essay coach persona.

    Returns {"feedback": str, "model": str}. Raises whatever `ollama.chat`
    raises on failure — callers (the router) decide how to surface that.
    """
    user_content = text
    if prompt_hint:
        user_content = f"Essay prompt: {prompt_hint}\n\nEssay:\n{text}"
    messages = [
        ChatMessage(role="system", content=_ESSAY_COACH_SYSTEM),
        ChatMessage(role="user", content=user_content),
    ]
    resp = await ollama.chat(messages)
    return {"feedback": resp.message.content, "model": resp.model}


def _application_to_item(app: Any) -> dict:
    context = getattr(app, "org", "") or getattr(app, "type", "")
    return {
        "kind": "application",
        "id": app.id,
        "title": app.name,
        "due": app.deadline,
        "context": context,
    }


def _assignment_to_item(assignment: Any) -> dict:
    return {
        "kind": "assignment",
        "id": assignment.id,
        "title": assignment.title,
        "due": assignment.due,
        "context": assignment.course_id,
    }


def deadline_digest(days: int = 14) -> dict:
    """Merge upcoming application deadlines + assignment due dates.

    Deterministic, no LLM call — safe to hit on every page load. Each
    foreign service call is isolated: if ApplicationsService or
    CoursesService is missing/broken, that source is silently skipped
    and the digest still returns whatever the other one had.
    """
    items: list[dict] = []

    try:
        apps_service = _get_applications_service()
        for app in apps_service.upcoming_deadlines(days=days):
            items.append(_application_to_item(app))
    except Exception:
        pass

    try:
        courses_service = _get_courses_service()
        for assignment in courses_service.due_soon(days=days):
            items.append(_assignment_to_item(assignment))
    except Exception:
        pass

    items.sort(key=lambda i: i["due"] or "9999-99-99")

    if not items:
        summary = f"No deadlines in the next {days} days."
    else:
        lines = [f"{len(items)} item(s) due in the next {days} days:"]
        for it in items:
            ctx = f" ({it['context']})" if it["context"] else ""
            lines.append(f"- [{it['kind']}] {it['title']}{ctx} — due {it['due']}")
        summary = "\n".join(lines)

    return {"items": items, "summary": summary}


async def deadline_digest_llm(ollama: Any, days: int = 14) -> dict:
    """deadline_digest() plus one Ollama call turning it into a briefing."""
    digest = deadline_digest(days=days)
    messages = [
        ChatMessage(role="system", content=_BRIEFING_SYSTEM),
        ChatMessage(role="user", content=digest["summary"]),
    ]
    resp = await ollama.chat(messages)
    return {
        "items": digest["items"],
        "summary": digest["summary"],
        "briefing": resp.message.content,
        "model": resp.model,
    }
