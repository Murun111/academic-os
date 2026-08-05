"""Agent tools over the academic modules.

- academics.upcoming_deadlines — read-only merged deadline view (delegates to
  routines.deadline_digest, which already merges applications + courses).
- academics.add_application — creates a card in the Applications pipeline.
  Deliberately NOT in autonomy's read/internal sets, so in the default
  cautious posture every call is gated behind the Approvals queue: the
  scholarship scout proposes, the student clicks approve.
"""
from __future__ import annotations

from backend.services.routines import deadline_digest

_apps_service = None

APPLICATION_TYPES = ("undergrad", "grad", "scholarship", "exchange")


def _apps():
    global _apps_service
    if _apps_service is None:
        from backend.services.applications import ApplicationsService
        from backend.vault import agentic_os_dir
        _apps_service = ApplicationsService(data_dir=agentic_os_dir() / "data" / "applications")
    return _apps_service


def reset_services() -> None:  # for tests
    global _apps_service
    _apps_service = None


async def upcoming_deadlines(days: int = 14) -> dict:
    """Merged application + assignment deadlines for the next N days."""
    days = max(1, min(int(days), 90))
    return deadline_digest(days=days)


async def student_profile() -> dict:
    """Read-only stage/track profile so agents can tailor searches.

    Deliberately excludes the student's name — agents don't need it.
    """
    from backend.routers.profile import get_profile
    p = get_profile()
    return {"stage": p.get("stage"), "track": p.get("track"), "test_date": p.get("test_date", "")}


async def add_application(
    name: str,
    type: str = "scholarship",
    deadline: str | None = None,
    org: str = "",
    url: str = "",
    notes: str = "",
) -> dict:
    """Create an application card (lands in the Researching column)."""
    name = (name or "").strip()
    if not name:
        return {"error": "name_required"}
    if type not in APPLICATION_TYPES:
        return {"error": "bad_type", "allowed": list(APPLICATION_TYPES)}
    item = _apps().add(
        name=name, type=type, deadline=deadline or None, org=org or "",
        url=url or "", notes=(notes or "") + "\n[agent-found — verify deadline on the official page]",
    )
    return {"ok": True, "id": item.id, "name": item.name, "status": item.status}
