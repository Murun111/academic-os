"""Tests for the Canvas REST connector."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.services.canvas_sync import CanvasSyncService, _iso_date
from backend.services.courses import CoursesService
from backend.routers.connectors import router, reset_services

COURSES_JSON = [
    {"id": 101, "name": "Intro to Chemistry", "course_code": "CHEM 110",
     "term": {"name": "Fall 2026"},
     "enrollments": [{"computed_current_score": 91.27}]},
    {"id": 102, "name": "World History", "course_code": "HIST 205"},
]

ASSIGNMENTS_JSON = {
    101: [
        {"id": 9001, "name": "Lab Report 1", "due_at": "2026-09-15T23:59:00Z",
         "points_possible": 20, "submission": {"workflow_state": "graded", "score": 18}},
        {"id": 9002, "name": "Problem Set 2", "due_at": "2026-09-22T23:59:00Z",
         "points_possible": 10, "submission": {"workflow_state": "unsubmitted"}},
    ],
    102: [
        {"id": 9003, "name": "Essay outline", "due_at": None,
         "points_possible": None, "submission": {"workflow_state": "submitted"}},
    ],
}


class FakeResponse:
    def __init__(self, payload): self._payload = payload
    def raise_for_status(self): pass
    def json(self): return self._payload


class FakeClient:
    def __init__(self, *a, **kw): pass
    async def __aenter__(self): return self
    async def __aexit__(self, *a): return False
    async def get(self, url, params=None):
        if url.endswith("/api/v1/courses"):
            return FakeResponse(COURSES_JSON)
        for cid, payload in ASSIGNMENTS_JSON.items():
            if f"/courses/{cid}/assignments" in url:
                return FakeResponse(payload)
        raise AssertionError(f"unexpected url {url}")


@pytest.fixture
def services(tmp_path, monkeypatch):
    monkeypatch.setattr("backend.services.canvas_sync.httpx.AsyncClient", FakeClient)
    canvas = CanvasSyncService(data_dir=tmp_path / "connectors")
    courses = CoursesService(data_dir=tmp_path / "courses")
    canvas.set_credentials("https://school.instructure.com", "tok_1234567890")
    return canvas, courses


def test_iso_date():
    assert _iso_date("2026-09-15T23:59:00Z") == "2026-09-15"
    assert _iso_date(None) is None


def test_masked_config_never_leaks_token(tmp_path):
    svc = CanvasSyncService(data_dir=tmp_path)
    svc.set_credentials("https://x.instructure.com/", "secret_token_abcd")
    m = svc.masked_config()
    assert m["connected"] is True
    assert m["token_hint"] == "…abcd"
    assert "secret_token_abcd" not in str(m)
    assert m["base_url"] == "https://x.instructure.com"  # trailing slash stripped


@pytest.mark.asyncio
async def test_sync_creates_courses_and_assignments(services):
    canvas, courses = services
    result = await canvas.sync(courses)
    assert result["courses"] == 2 and result["created"] == 3 and not result["errors"]
    by_ext = {c.external_id: c for c in courses.list_courses()}
    assert by_ext["canvas-101"].name == "Intro to Chemistry"
    assert by_ext["canvas-101"].term == "Fall 2026"
    assert by_ext["canvas-102"].term == "Canvas"  # no term in payload
    a = {x.external_id: x for x in courses.list_assignments()}
    assert a["canvas-a-9001"].status == "done"      # graded → done
    assert a["canvas-a-9001"].grade == 90.0         # 18/20
    assert a["canvas-a-9002"].status == "todo"
    assert a["canvas-a-9003"].status == "done"      # submitted → done
    assert a["canvas-a-9003"].due is None


@pytest.mark.asyncio
async def test_sync_idempotent_and_never_demotes(services):
    canvas, courses = services
    await canvas.sync(courses)
    # student manually marks the unsubmitted one done + enters a grade
    a = {x.external_id: x for x in courses.list_assignments()}
    courses.update_assignment(a["canvas-a-9002"].id, status="done", grade=77.0)
    result = await canvas.sync(courses)
    assert result["created"] == 0
    a2 = {x.external_id: x for x in courses.list_assignments()}
    assert a2["canvas-a-9002"].status == "done"   # not reverted to todo
    assert a2["canvas-a-9002"].grade == 77.0      # manual grade kept
    assert len(courses.list_assignments()) == 3   # no duplicates


@pytest.mark.asyncio
async def test_sync_without_credentials_reports_error(tmp_path, monkeypatch):
    monkeypatch.setattr("backend.services.canvas_sync.httpx.AsyncClient", FakeClient)
    canvas = CanvasSyncService(data_dir=tmp_path / "c")
    courses = CoursesService(data_dir=tmp_path / "k")
    result = await canvas.sync(courses)
    assert result["errors"] and result["errors"][0]["scope"] == "config"


# ── router ────────────────────────────────────────────────────────

@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("ACADEMIC_OS_DATA", str(tmp_path))
    monkeypatch.setattr("backend.services.canvas_sync.httpx.AsyncClient", FakeClient)
    reset_services()
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as c:
        yield c
    reset_services()


def test_canvas_router_flow(client):
    assert client.get("/api/connectors/canvas").json()["connected"] is False
    assert client.post("/api/connectors/canvas/sync").status_code == 400
    r = client.post("/api/connectors/canvas",
                    json={"base_url": "https://school.instructure.com", "token": "tok_1234567890"})
    assert r.status_code == 200 and r.json()["connected"] is True
    r = client.post("/api/connectors/canvas/sync")
    assert r.status_code == 200 and r.json()["created"] == 3
    r = client.post("/api/connectors/canvas/clear")
    assert r.json()["connected"] is False


def test_canvas_router_rejects_short_token(client):
    r = client.post("/api/connectors/canvas",
                    json={"base_url": "https://school.instructure.com", "token": "abc"})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_sync_pulls_course_total_grade(services):
    canvas, courses = services
    await canvas.sync(courses)
    chem = next(c for c in courses.list_courses() if c.external_id == "canvas-101")
    hist = next(c for c in courses.list_courses() if c.external_id == "canvas-102")
    assert chem.canvas_score == 91.3  # rounded to one decimal
    assert hist.canvas_score is None  # no enrollments in payload


@pytest.mark.asyncio
async def test_canvas_score_always_refreshes(services):
    """Unlike assignment grades, the course total is Canvas-owned — resync overwrites."""
    canvas, courses = services
    await canvas.sync(courses)
    chem = next(c for c in courses.list_courses() if c.external_id == "canvas-101")
    courses.set_canvas_score(chem.id, 50.0)  # simulate stale value
    await canvas.sync(courses)
    chem = next(c for c in courses.list_courses() if c.external_id == "canvas-101")
    assert chem.canvas_score == 91.3
