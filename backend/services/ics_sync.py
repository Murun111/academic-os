"""ICS calendar-feed sync — the universal LMS connector.

Nearly every LMS (Canvas, Moodle, Brightspace, most Blackboard installs)
gives each student a private ICS feed URL of their due dates. This service
fetches those feeds and upserts the events as assignments in the Courses
module, keyed by the ICS UID so re-syncing updates instead of duplicating.

Deliberately dependency-free: a minimal VEVENT parser (SUMMARY / DTSTART /
UID / DTEND) rather than an icalendar library — feeds only need those four.

Config lives at data/connectors/ics.json:
    {"feeds": ["https://..."], "last_sync": iso, "last_result": {...}}

Each feed URL embeds a per-student secret token (e.g. Canvas's
`.../feeds/calendars/user_XXXX.ics`) — treat it as a credential. `config()`
returns the raw list for internal use (adding feeds, syncing); anything
that crosses to the client goes through `masked_config()` instead, which
reduces each feed to `{id, host, configured}`.
"""
from __future__ import annotations

import json
import os
import re
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import httpx


class _FeedBlocked(Exception):
    """A feed URL (or a redirect hop) resolved to a blocked destination."""


async def _guarded_ics_get(url: str) -> httpx.Response:
    """GET an ICS feed with SSRF protection.

    Guards the initial URL and every redirect hop against
    loopback/private/link-local addresses — a feed host can 30x-redirect into
    127.0.0.1 or a LAN service otherwise. Redirects are followed manually (not
    via httpx follow_redirects) so each hop is re-guarded before the request.
    """
    from backend.services.websearch import _ssrf_guard  # local: avoid import cycle

    current = url
    async with httpx.AsyncClient(timeout=20, follow_redirects=False) as client:
        for _ in range(6):  # cap the redirect chain
            blocked = _ssrf_guard(current)
            if blocked is not None:
                raise _FeedBlocked(blocked.get("detail", "blocked destination"))
            r = await client.get(current)
            if r.is_redirect and r.next_request is not None:
                current = str(r.next_request.url)
                continue
            r.raise_for_status()
            return r
    raise _FeedBlocked("too many redirects")


# ── minimal ICS parsing ──────────────────────────────────────────

@dataclass
class IcsEvent:
    uid: str
    summary: str
    due: str | None  # ISO date
    recurrence_id: str = ""  # set on a modified/recurring instance


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


def _parse_dt(value: str, params: str = "") -> str | None:
    """ICS date or datetime -> ISO date string in the student's LOCAL timezone.

    All-day values (VALUE=DATE / 8 digits) keep their calendar date. A UTC
    value ('...Z') or one carrying TZID is converted to local time first, so a
    deadline of 11:59pm US Eastern ('20260916T035900Z') lands on the 15th, not
    the 16th. Floating times keep their date part."""
    value = value.strip()
    m = re.match(r"^(\d{4})(\d{2})(\d{2})(?:T(\d{2})(\d{2})(\d{2})?(Z)?)?", value, re.I)
    if not m:
        return None
    y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    try:
        day = date(y, mo, d)
    except ValueError:
        return None
    if m.group(4) is None:
        return day.isoformat()
    try:
        dt = datetime(y, mo, d, int(m.group(4)), int(m.group(5)), int(m.group(6) or 0))
    except ValueError:
        return day.isoformat()
    tz = None
    if m.group(7):
        tz = timezone.utc
    else:
        tzid = re.search(r"TZID=([^;:]+)", params, re.I)
        if tzid:
            try:
                from zoneinfo import ZoneInfo
                tz = ZoneInfo(tzid.group(1).strip('"'))
            except Exception:  # noqa: BLE001 - unknown zone: keep the raw date
                tz = None
    if tz is None:
        return day.isoformat()
    return dt.replace(tzinfo=tz).astimezone().date().isoformat()


def parse_ics(text: str) -> list[IcsEvent]:
    """Extract VEVENTs. Tolerant: events missing a UID or SUMMARY are skipped;
    DTSTART params (;VALUE=DATE, ;TZID=...) are ignored — the date part is
    all we keep."""
    events: list[IcsEvent] = []
    cur: dict[str, str] | None = None
    for line in _unfold(text):
        key, _, value = line.partition(":")
        name = key.split(";")[0].upper()
        params = key.partition(";")[2]
        if name == "BEGIN" and value.strip().upper() == "VEVENT":
            cur = {}
        elif name == "END" and value.strip().upper() == "VEVENT":
            if cur is not None and cur.get("uid") and cur.get("summary"):
                events.append(IcsEvent(uid=cur["uid"], summary=cur["summary"],
                                       due=cur.get("due"),
                                       recurrence_id=cur.get("rid", "")))
            cur = None
        elif cur is not None:
            if name == "UID":
                cur["uid"] = value.strip()
            elif name == "SUMMARY":
                cur["summary"] = _unescape(value)
            elif name == "RECURRENCE-ID":
                cur["rid"] = value.strip()
            elif name in ("DTSTART", "DTEND", "DUE") and "due" not in cur:
                iso = _parse_dt(value, params)
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


def _safe_error(exc: Exception, url: str, host: str) -> str:
    """Error text for the client: the feed URL embeds a secret token and
    httpx puts it in HTTPStatusError's message, so never pass str(exc) raw."""
    if isinstance(exc, httpx.HTTPStatusError):
        return f"HTTP {exc.response.status_code}"
    msg = str(exc)
    for needle in (url, url.split("?")[0]):
        if needle:
            msg = msg.replace(needle, host or "feed")
    return f"{type(exc).__name__}: {msg}"


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

    def remove_feed_by_id(self, feed_id: int) -> dict:
        """Unregister a feed by its position in the list (the `id` handed out
        by `masked_config()`) — the caller never has to round-trip the full
        URL, which carries a per-student secret token."""
        cfg = self.config()
        if 0 <= feed_id < len(cfg["feeds"]):
            del cfg["feeds"][feed_id]
            self._save(cfg)
        return cfg

    def masked_config(self) -> dict:
        """Config safe to return to the UI. Canvas/Moodle/Brightspace feed
        URLs embed a per-student secret token in the path — never send the
        full URL to the client, only its host and a stable-for-this-list id
        (`config()` / `sync()` keep using the raw URL internally)."""
        cfg = self.config()
        feeds = []
        for i, url in enumerate(cfg["feeds"]):
            try:
                host = urlparse(url).hostname or ""
            except ValueError:
                host = ""
            feeds.append({"id": i, "host": host, "configured": True})
        return {"feeds": feeds, "last_sync": cfg.get("last_sync"),
                "last_result": cfg.get("last_result")}

    # sync ---------------------------------------------------------
    async def sync(self, courses_service) -> dict:
        """Fetch every feed and upsert assignments. Never raises on a bad
        feed — per-feed errors are reported in the result."""
        cfg = self.config()
        result = {"feeds": len(cfg["feeds"]), "created": 0, "updated": 0,
                  "unchanged": 0, "errors": []}

        for i, url in enumerate(cfg["feeds"]):
            # Error records are surfaced via masked_config() → the client, so
            # they carry only the masked id/host, never the raw URL (which
            # embeds the per-student secret token).
            try:
                host = urlparse(url).hostname or ""
            except ValueError:
                host = ""
            try:
                r = await _guarded_ics_get(url)
                events = parse_ics(r.text)
            except Exception as e:
                result["errors"].append(
                    {"feed_id": i, "host": host, "error": _safe_error(e, url, host)})
                continue

            courses = {c.name: c for c in courses_service.list_courses()}
            existing = {a.external_id: a for a in courses_service.list_assignments()
                        if a.external_id}

            # Events sharing a UID (recurring instances) need distinct keys,
            # otherwise one stored row flip-flops between their dates. Plain
            # UID stays the key for ordinary events (existing data keeps matching).
            uid_counts: dict[str, int] = {}
            for ev in events:
                uid_counts[ev.uid] = uid_counts.get(ev.uid, 0) + 1
            claimed: set[str] = set()

            for ev in events:
                title, course_name = split_course(ev.summary)
                if course_name in courses and courses[course_name].source == "canvas":
                    # Canvas already syncs this course with richer data; a feed
                    # copy would just re-create a duplicate after removal.
                    result["skipped_canvas"] = result.get("skipped_canvas", 0) + 1
                    continue
                if course_name not in courses:
                    # term is required by the service; synced courses get a
                    # marker term the student can rename
                    courses[course_name] = courses_service.add_course(
                        name=course_name, term="Synced", instructor="", source="ics")
                course = courses[course_name]

                key = ev.uid
                if ev.recurrence_id or uid_counts[ev.uid] > 1:
                    key = f"{ev.uid}#{ev.recurrence_id or ev.due or ''}"
                prev = existing.get(key)
                if prev is None and key != ev.uid:
                    legacy = existing.get(ev.uid)
                    if legacy is not None and legacy.id not in claimed and legacy.due == ev.due:
                        prev = legacy  # adopt the row stored before keys were split
                if prev is not None:
                    claimed.add(prev.id)
                if prev is None:
                    created = courses_service.add_assignment(
                        course_id=course.id, title=title, due=ev.due,
                        source="ics", external_id=key)
                    existing[key] = created
                    claimed.add(created.id)
                    result["created"] += 1
                elif prev.title != title or prev.due != ev.due:
                    # update sync-owned fields only — status/grade/notes are
                    # the student's and never clobbered
                    courses_service.update_assignment(prev.id, title=title, due=ev.due)
                    prev.title, prev.due = title, ev.due
                    result["updated"] += 1
                else:
                    result["unchanged"] += 1

        cfg["last_sync"] = datetime.now(timezone.utc).isoformat()
        cfg["last_result"] = result
        self._save(cfg)
        return result
