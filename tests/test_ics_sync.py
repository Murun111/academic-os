"""Tests for the ICS calendar-feed connector."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.services.courses import CoursesService
from backend.services.ics_sync import IcsSyncService, parse_ics, split_course
from backend.routers import connectors as connectors_module
from backend.routers.connectors import router, reset_services

SAMPLE_ICS = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Instructure//Canvas//EN
BEGIN:VEVENT
UID:event-assignment-1@canvas
DTSTART;VALUE=DATE:20260915
SUMMARY:Problem Set 3 [MATH 201]
END:VEVENT
BEGIN:VEVENT
UID:event-assignment-2@canvas
DTSTART:20260920T235900Z
SUMMARY:Essay draft\\, part one [ENGL 101]
END:VEVENT
BEGIN:VEVENT
UID:event-no-course@canvas
DTSTART;VALUE=DATE:20260918
SUMMARY:Advising appointment
END:VEVENT
BEGIN:VEVENT
DTSTART;VALUE=DATE:20260919
SUMMARY:No UID — skipped
END:VEVENT
END:VCALENDAR
"""


# ── parser ────────────────────────────────────────────────────────

@pytest.fixture
def tz(monkeypatch):
    import time

    def _set(name):
        monkeypatch.setenv("TZ", name)
        time.tzset()
    yield _set
    monkeypatch.delenv("TZ", raising=False)
    time.tzset()


def test_parse_ics_extracts_events(tz):
    tz("UTC")
    events = parse_ics(SAMPLE_ICS)
    assert len(events) == 3  # the UID-less one is skipped
    assert events[0].uid == "event-assignment-1@canvas"
    assert events[0].summary == "Problem Set 3 [MATH 201]"
    assert events[0].due == "2026-09-15"
    assert events[1].due == "2026-09-20"  # datetime → date
    assert events[1].summary == "Essay draft, part one [ENGL 101]"  # unescaped


def test_parse_ics_line_folding():
    folded = "BEGIN:VCALENDAR\nBEGIN:VEVENT\nUID:u1\nSUMMARY:Long titl\n e continues [BIO 1]\nDTSTART:20260901\nEND:VEVENT\nEND:VCALENDAR\n"
    events = parse_ics(folded)
    assert events[0].summary == "Long title continues [BIO 1]"


def test_split_course():
    assert split_course("Problem Set 3 [MATH 201]") == ("Problem Set 3", "MATH 201")
    assert split_course("Advising appointment") == ("Advising appointment", "Synced calendar")


# ── sync upsert ───────────────────────────────────────────────────

class FakeResponse:
    is_redirect = False  # sync() now follows redirects manually via _guarded_ics_get
    def __init__(self, text): self.text = text
    def raise_for_status(self): pass


class FakeClient:
    def __init__(self, *a, **kw): pass
    async def __aenter__(self): return self
    async def __aexit__(self, *a): return False
    async def get(self, url, *a, **kw): return FakeResponse(SAMPLE_ICS)


def _resolve_public(host, *a, **k):
    """Make any feed host resolve to a public IP so the ICS SSRF guard passes
    (real .example hosts are unresolvable). Keeps tests off real DNS."""
    import socket as _s
    return [(_s.AF_INET, _s.SOCK_STREAM, 6, "", ("93.184.216.34", 0))]


@pytest.fixture
def services(tmp_path, monkeypatch):
    monkeypatch.setattr("backend.services.ics_sync.httpx.AsyncClient", FakeClient)
    monkeypatch.setattr("backend.services.websearch.socket.getaddrinfo", _resolve_public)
    ics = IcsSyncService(data_dir=tmp_path / "connectors")
    courses = CoursesService(data_dir=tmp_path / "courses")
    ics.add_feed("https://school.example/feeds/user_abc.ics")
    return ics, courses


@pytest.mark.asyncio
async def test_sync_creates_courses_and_assignments(services):
    ics, courses = services
    result = await ics.sync(courses)
    assert result["created"] == 3 and not result["errors"]
    names = {c.name for c in courses.list_courses()}
    assert names == {"MATH 201", "ENGL 101", "Synced calendar"}
    a = next(x for x in courses.list_assignments() if x.title == "Problem Set 3")
    assert a.source == "ics" and a.external_id == "event-assignment-1@canvas"
    assert a.due == "2026-09-15"


@pytest.mark.asyncio
async def test_sync_is_idempotent_and_preserves_student_fields(services):
    ics, courses = services
    await ics.sync(courses)
    # student marks one done — a re-sync must not clobber it
    a = next(x for x in courses.list_assignments() if x.title == "Problem Set 3")
    courses.update_assignment(a.id, status="done")
    result = await ics.sync(courses)
    assert result["created"] == 0 and result["unchanged"] == 3
    a2 = next(x for x in courses.list_assignments() if x.title == "Problem Set 3")
    assert a2.status == "done"
    assert len(courses.list_assignments()) == 3


@pytest.mark.asyncio
async def test_sync_bad_feed_reports_error_not_raise(tmp_path, monkeypatch):
    class BoomClient(FakeClient):
        async def get(self, url): raise OSError("connection refused")
    monkeypatch.setattr("backend.services.ics_sync.httpx.AsyncClient", BoomClient)
    ics = IcsSyncService(data_dir=tmp_path / "connectors")
    courses = CoursesService(data_dir=tmp_path / "courses")
    ics.add_feed("https://dead.example/feed.ics")
    result = await ics.sync(courses)
    assert len(result["errors"]) == 1
    assert result["created"] == 0


# ── router ────────────────────────────────────────────────────────

@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("ACADEMIC_OS_DATA", str(tmp_path))
    monkeypatch.setattr("backend.services.ics_sync.httpx.AsyncClient", FakeClient)
    monkeypatch.setattr("backend.services.websearch.socket.getaddrinfo", _resolve_public)
    reset_services()
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as c:
        yield c
    reset_services()


def test_router_add_status_sync_flow(client):
    assert client.get("/api/connectors/ics").json()["feeds"] == []
    r = client.post("/api/connectors/ics", json={"url": "https://school.example/f.ics"})
    assert r.status_code == 200 and len(r.json()["feeds"]) == 1
    r = client.post("/api/connectors/ics/sync")
    assert r.status_code == 200
    assert r.json()["created"] == 3
    status = client.get("/api/connectors/ics").json()
    assert status["last_sync"] is not None


def test_router_sync_without_feeds_400(client):
    assert client.post("/api/connectors/ics/sync").status_code == 400


def test_router_rejects_non_url(client):
    assert client.post("/api/connectors/ics", json={"url": "not a url"}).status_code == 422


def test_parse_ics_converts_to_local_date(tz):
    tz("America/New_York")
    text = (
        "BEGIN:VEVENT\nUID:a\nSUMMARY:Utc [C]\nDTSTART:20260916T035900Z\nEND:VEVENT\n"
        "BEGIN:VEVENT\nUID:b\nSUMMARY:Zoned [C]\nDTSTART;TZID=America/Chicago:20260915T235900\nEND:VEVENT\n"
        "BEGIN:VEVENT\nUID:c\nSUMMARY:AllDay [C]\nDTSTART;VALUE=DATE:20260916\nEND:VEVENT\n"
        "BEGIN:VEVENT\nUID:d\nSUMMARY:Float [C]\nDTSTART:20260916T010000\nEND:VEVENT\n"
    )
    by = {e.uid: e.due for e in parse_ics(text)}
    assert by["a"] == "2026-09-15"   # 11:59pm Eastern, not the 16th
    assert by["b"] == "2026-09-16"   # 23:59 Chicago = 00:59 Eastern next day
    assert by["c"] == "2026-09-16"   # all-day keeps its calendar date
    assert by["d"] == "2026-09-16"   # floating keeps its date


DUP_UID_ICS = """BEGIN:VCALENDAR
BEGIN:VEVENT
UID:same
DTSTART;VALUE=DATE:20261101
SUMMARY:Seminar [BIO 1]
END:VEVENT
BEGIN:VEVENT
UID:same
DTSTART;VALUE=DATE:20261102
SUMMARY:Seminar [BIO 1]
END:VEVENT
END:VCALENDAR
"""


@pytest.mark.asyncio
async def test_same_uid_events_are_stable_across_syncs(services, monkeypatch):
    ics, courses = services

    class DupClient(FakeClient):
        async def get(self, url, *a, **kw): return FakeResponse(DUP_UID_ICS)

    monkeypatch.setattr("backend.services.ics_sync.httpx.AsyncClient", DupClient)
    first = await ics.sync(courses)
    assert first["created"] == 2
    second = await ics.sync(courses)
    assert second["created"] == 0 and second["updated"] == 0 and second["unchanged"] == 2
    assert sorted(a.due for a in courses.list_assignments()) == ["2026-11-01", "2026-11-02"]


@pytest.mark.asyncio
async def test_ics_skips_events_for_canvas_synced_course(services):
    ics, courses = services
    courses.add_course(name="MATH 201", term="Fall", source="canvas", external_id="canvas-1")
    result = await ics.sync(courses)
    assert result["skipped_canvas"] == 1
    assert all(c.source != "ics" or c.name != "MATH 201" for c in courses.list_courses())
    assert not [a for a in courses.list_assignments() if a.title == "Problem Set 3"]


@pytest.mark.asyncio
async def test_http_error_does_not_leak_feed_url(tmp_path, monkeypatch):
    import httpx

    secret = "https://canvas.example.edu/feeds/calendars/user_SECRETTOKEN123.ics"
    monkeypatch.setattr("backend.services.websearch.socket.getaddrinfo", _resolve_public)

    class C401(FakeClient):
        async def get(self, url, *a, **kw):
            req = httpx.Request("GET", url)
            resp = httpx.Response(401, request=req)
            class R:
                is_redirect = False
                def raise_for_status(self_inner):
                    raise httpx.HTTPStatusError("Client error for url " + url, request=req, response=resp)
            return R()

    monkeypatch.setattr("backend.services.ics_sync.httpx.AsyncClient", C401)
    ics = IcsSyncService(data_dir=tmp_path / "connectors")
    courses = CoursesService(data_dir=tmp_path / "courses")
    ics.add_feed(secret)
    result = await ics.sync(courses)
    assert result["errors"][0]["error"] == "HTTP 401"
    assert "SECRETTOKEN123" not in str(result)
    assert "SECRETTOKEN123" not in str(ics.masked_config())
