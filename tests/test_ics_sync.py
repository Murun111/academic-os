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

def test_parse_ics_extracts_events():
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
    def __init__(self, text): self.text = text
    def raise_for_status(self): pass


class FakeClient:
    def __init__(self, *a, **kw): pass
    async def __aenter__(self): return self
    async def __aexit__(self, *a): return False
    async def get(self, url): return FakeResponse(SAMPLE_ICS)


@pytest.fixture
def services(tmp_path, monkeypatch):
    monkeypatch.setattr("backend.services.ics_sync.httpx.AsyncClient", FakeClient)
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
