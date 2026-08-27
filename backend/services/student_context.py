"""Ground local-AI chat in the student's real situation.

Assembles a compact snapshot — profile/stage/track/exam, the merged deadline
digest (applications + assignments), and the student's own open tasks this week
— so the model answers "what should I focus on?" from actual data instead of
guessing. Best-effort: every source is isolated, and a broken one is skipped
rather than failing the chat. Trusted data (the student's own records), but
framed as reference, never as instructions.
"""
from __future__ import annotations

# Char budget — the grounding block rides in front of every chat turn, and the
# bundled model is small, so keep it tight.
_MAX_CHARS = 1400


def build_context() -> str:
    """A compact grounding block, or '' when there's nothing to ground on."""
    parts: list[str] = []

    # 1. Profile: stage / track / exam date — cheap, sets the frame.
    try:
        from backend.routers.profile import get_profile
        p = get_profile()
        bits = []
        if p.get("stage"):
            bits.append(f"stage {p['stage']}")
        if p.get("track"):
            bits.append(f"track {p['track']}")
        if p.get("test_date"):
            bits.append(f"exam date {p['test_date']}")
        if bits:
            parts.append("Profile: " + ", ".join(bits) + ".")
    except Exception:
        pass

    # 2. Deadlines + assignments due in the next 2 weeks (already merged +
    #    formatted by the deadline digest — reuse its human-readable summary).
    try:
        from backend.services.routines import deadline_digest
        dd = deadline_digest(days=14)
        # Only ground on ACTUAL items — the digest returns a "No deadlines"
        # summary even when empty, which is noise, not grounding.
        if (dd or {}).get("items"):
            parts.append(dd["summary"])
    except Exception:
        pass

    # 3. The student's OWN open tasks this week (kind == task, not done).
    try:
        from backend.services.study import StudyService
        from backend.vault import agentic_os_dir
        svc = StudyService(data_dir=agentic_os_dir() / "data" / "study")
        agenda = svc.agenda(days=7)
        tasks = [
            it for it in (agenda.get("items") or [])
            if it.get("kind") == "task" and not (it.get("meta") or {}).get("done")
        ]
        if tasks:
            lines = ["Your tasks this week:"]
            for it in tasks[:8]:
                when = it.get("date")
                lines.append(f"- {it.get('title')}" + (f" (due {when})" if when else ""))
            parts.append("\n".join(lines))
    except Exception:
        pass

    if not parts:
        return ""

    body = "\n\n".join(parts)
    if len(body) > _MAX_CHARS:
        body = body[:_MAX_CHARS].rsplit("\n", 1)[0] + "\n…"

    return (
        "The student's current data — use ONLY this to answer questions about "
        "their deadlines, courses, and tasks. Never invent items that are not "
        "listed here; if something is not in this data, say you do not have it.\n\n"
        + body
    )
