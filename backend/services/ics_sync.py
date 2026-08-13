"""ICS calendar-feed sync — the universal LMS connector.

Nearly every LMS (Canvas, Moodle, Brightspace, most Blackboard installs)
gives each student a private ICS feed URL of their due dates. This service
fetches those feeds and upserts the events as assignments in the Courses
module, keyed by the ICS UID so re-syncing updates instead of duplicating.

Deliberately dependency-free: a minimal VEVENT parser (SUMMARY / DTSTART /
UID / DTEND) rather than an icalendar library — feeds only need those four.

Config lives at data/connectors/ics.json:
    {"feeds": ["https://..."], "last_sync": iso, "last_result": {...}}
"""
from __future__ import annotations

import json
import os
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import httpx


# ── minimal ICS parsing ──────────────────────────────────────────

@dataclass
class IcsEvent:
    uid: str
    summary: str
    due: str | None  # ISO date


def _unfold(text: str) -> list[str]:
    """RFC 5545 line unfolding: a line starting with space/tab continues the
    previous line."""
    out: list[str] = []
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if raw[:1] in (" ", "\t") and out:
            out[-1] += raw[1:]
        else:
            out.append(raw)
    return out


def _unescape(v: str) -> str:
    return v.replace("\\n", " ").replace("\\,", ",").replace("\\;", ";").strip()


def _parse_dt(value: str) -> str | None:
    """ICS date or datetime → ISO date string (we only need the day)."""
    value = value.strip()
    m = re.match(r"^(\d{4})(\d{2})(\d{2})", value)
    if not m:
        return None
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"


def parse_ics(text: str) -> list[IcsEvent]:
    """Extract VEVENTs. Tolerant: events missing a UID or SUMMARY are skipped;
    DTSTART params (;VALUE=DATE, ;TZID=...) are ignored — the date part is
    all we keep."""
    events: list[IcsEvent] = []
    cur: dict[str, str] | None = None
    for line in _unfold(text):
        key, _, value = line.partition(":")
        name = key.split(";")[0].upper()
        if name == "BEGIN" and value.strip().upper() == "VEVENT":
            cur = {}
        elif name == "END" and value.strip().upper() == "VEVENT":
            if cur is not None and cur.get("uid") and cur.get("summary"):
                events.append(IcsEvent(uid=cur["uid"], summary=cur["summary"],
                                       due=cur.get("due")))
            cur = None
        elif cur is not None:
            if name == "UID":
                cur["uid"] = value.strip()
            elif name == "SUMMARY":
                cur["summary"] = _unescape(value)
            elif name in ("DTSTART", "DTEND", "DUE") and "due" not in cur:
                iso = _parse_dt(value)
                if iso:
                    cur["due"] = iso
    return events


# Canvas titles its feed events "Assignment Name [Course Name]".
_COURSE_IN_BRACKETS = re.compile(r"^(.*)\s+\[([^\]]+)\]\s*$")


def split_course(summary: str) -> tuple[str, str]:
    """→ (title, course_name). Falls back to a catch-all course."""
    m = _COURSE_IN_BRACKETS.match(summary)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    return summary.strip(), "Synced calendar"


# ── sync service ─────────────────────────────────────────────────

class IcsSyncService:
    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._path = self.data_dir / "ics.json"

    # config -------------------------------------------------------
    def config(self) -> dict:
        if self._path.exists():
            try:
                return json.loads(self._path.read_text())
            except (json.JSONDecodeError, OSError):
                pass
        return {"feeds": [], "last_sync": None, "last_result": None}

    def _save(self, cfg: dict) -> None:
        """Write config atomically: tmp file in the same dir, then replace."""
        p = self._path
        tmp = p.with_name(f".{p.name}.{uuid.uuid4().hex}.tmp")
        tmp.write_text(json.dumps(cfg, indent=2))
        os.replace(tmp, p)

    def add_feed(self, url: str) -> dict:
        cfg = self.config()
        if url not in cfg["feeds"]:
            cfg["feeds"].append(url)
            self._save(cfg)
        return cfg

    def remove_feed(self, url: str) -> dict:
        cfg = self.config()
        cfg["feeds"] = [f for f in cfg["feeds"] if f != url]
        self._save(cfg)
        return cfg

    # sync ---------------------------------------------------------
    async def sync(self, courses_service) -> dict:
        """Fetch every feed and upsert assignments. Never raises on a bad
        feed — per-feed errors are reported in the result."""
        cfg = self.config()
        result = {"feeds": len(cfg["feeds"]), "created": 0, "updated": 0,
                  "unchanged": 0, "errors": []}

        for url in cfg["feeds"]:
            try:
                async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
                    r = await client.get(url)
                    r.raise_for_status()
                events = parse_ics(r.text)
            except Exception as e:
                result["errors"].append({"feed": url[:80], "error": f"{type(e).__name__}: {e}"})
                continue

            courses = {c.name: c for c in courses_service.list_courses()}
            existing = {a.external_id: a for a in courses_service.list_assignments()
                        if a.external_id}

            for ev in events:
                title, course_name = split_course(ev.summary)
                if course_name not in courses:
                    # term is required by the service; synced courses get a
                    # marker term the student can rename
                    courses[course_name] = courses_service.add_course(
                        name=course_name, term="Synced", instructor="", source="ics")
                course = courses[course_name]

                prev = existing.get(ev.uid)
                if prev is None:
                    courses_service.add_assignment(
                        course_id=course.id, title=title, due=ev.due,
                        source="ics", external_id=ev.uid)
                    result["created"] += 1
                elif prev.title != title or prev.due != ev.due:
                    # update sync-owned fields only — status/grade/notes are
                    # the student's and never clobbered
                    courses_service.update_assignment(prev.id, title=title, due=ev.due)
                    result["updated"] += 1
                else:
                    result["unchanged"] += 1

        cfg["last_sync"] = datetime.now(timezone.utc).isoformat()
        cfg["last_result"] = result
        self._save(cfg)
        return result
