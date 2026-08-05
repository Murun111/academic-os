"""Daily deadline reminders — deterministic, no LLM.

While the app is running, check every 30 minutes whether today's reminder
has gone out; if not, build the 7-day deadline digest and pop ONE native
macOS notification (via services.notify). One per calendar day, ever.

State: data/notify_state.json {"last_sent": "YYYY-MM-DD"}.
Toggle: profile.json "reminders" (default true) — set from Settings.
"""
from __future__ import annotations

import asyncio
import json
from datetime import date
from pathlib import Path

from backend.services.notify import notify
from backend.services.routines import deadline_digest

CHECK_INTERVAL_SECONDS = 30 * 60
WINDOW_DAYS = 7


def _data_dir() -> Path:
    from backend.vault import agentic_os_dir
    d = agentic_os_dir() / "data"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _state_path() -> Path:
    return _data_dir() / "notify_state.json"


def reminders_enabled() -> bool:
    """Profile toggle; default ON (missing profile/field means enabled)."""
    try:
        p = _data_dir() / "profile.json"
        if p.exists():
            return bool(json.loads(p.read_text()).get("reminders", True))
    except (json.JSONDecodeError, OSError):
        pass
    return True


def _already_sent_today() -> bool:
    try:
        p = _state_path()
        if p.exists():
            return json.loads(p.read_text()).get("last_sent") == date.today().isoformat()
    except (json.JSONDecodeError, OSError):
        pass
    return False


def _mark_sent() -> None:
    _state_path().write_text(json.dumps({"last_sent": date.today().isoformat()}))


def build_summary(days: int = WINDOW_DAYS) -> tuple[str, str] | None:
    """(title, message) for the next-N-days digest, or None when nothing is due."""
    digest = deadline_digest(days=days)
    items = digest.get("items", [])
    if not items:
        return None
    first = items[0]
    due = first.get("due") or "soon"
    lead = f"{first.get('title', 'Untitled')} — {due}"
    n = len(items)
    title = f"{n} deadline{'s' if n != 1 else ''} in the next {days} days"
    message = lead if n == 1 else f"Next: {lead} (+{n - 1} more)"
    return title, message


def check_and_send(force: bool = False) -> dict:
    """One reminder per day. `force` skips the daily guard and the toggle
    (used by the Settings test button); forced sends never consume the day."""
    if not force:
        if not reminders_enabled():
            return {"sent": False, "reason": "disabled"}
        if _already_sent_today():
            return {"sent": False, "reason": "already_sent_today"}
    summary = build_summary()
    if summary is None:
        if not force:
            _mark_sent()  # nothing due — today's check is done
        return {"sent": False, "reason": "nothing_due"}
    title, message = summary
    notify(title, message)  # best-effort; no-op off macOS
    if not force:
        _mark_sent()
    return {"sent": True, "title": title, "message": message}


async def reminder_loop() -> None:
    """Background task: check shortly after startup, then every 30 minutes."""
    await asyncio.sleep(20)  # let the app finish booting first
    while True:
        try:
            result = check_and_send()
            if result.get("sent"):
                print(f"[deadline_reminders] sent: {result['title']}")
        except Exception as e:  # noqa: BLE001 — the loop must survive anything
            print(f"[deadline_reminders] check failed: {e!r}")
        await asyncio.sleep(CHECK_INTERVAL_SECONDS)
