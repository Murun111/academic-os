"""Tests for backend.services.routines + backend.routers.routines
(deadline watcher + essay feedback).

No real Ollama is ever called: a FakeOllama stands in everywhere. The
Applications/Courses services are owned by other modules being built in
parallel, so deadline_digest is exercised entirely through monkeypatched
fakes for `_get_applications_service` / `_get_courses_service` — this
works whether or not those real modules exist yet on disk.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.routers.routines import router as routines_router
from backend.services import routines as routines_service


# === fakes ===

class FakeOllama:
    def __init__(self, content: str = "looks good", model: str = "fake-model", fail: bool = False):
        self.content = content
        self.model = model
        self.fail = fail
        self.calls: list = []

    async def chat(self, messages, tools=None, think=False, model=None):
        self.calls.append(messages)
        if self.fail:
            raise RuntimeError("ollama unreachable")
        return SimpleNamespace(message=SimpleNamespace(content=self.content), model=self.model)


class FakeAppsService:
    def __init__(self, items):
        self._items = items

    def upcoming_deadlines(self, days: int = 30):
        return self._items


class FakeCoursesService:
    def __init__(self, items):
        self._items = items

    def due_soon(self, days: int = 14):
        return self._items


class RaisingService:
    def upcoming_deadlines(self, days: int = 30):
        raise RuntimeError("applications module broken")

    def due_soon(self, days: int = 14):
        raise RuntimeError("courses module broken")


def fake_application(id_, name, org, deadline, type_="grad"):
    return SimpleNamespace(id=id_, name=name, org=org, type=type_, deadline=deadline)


def fake_assignment(id_, title, due, course_id):
    return SimpleNamespace(id=id_, title=title, due=due, course_id=course_id)


@pytest.fixture(autouse=True)
def _isolated_data_dir(tmp_path, monkeypatch: pytest.MonkeyPatch):
    # Belt-and-suspenders: every test monkeypatches the foreign-service
    # getters directly, but point ACADEMIC_OS_DATA at a tmp dir too so a
    # stray real import/instantiation never touches ~/.academic-os.
    monkeypatch.setenv("ACADEMIC_OS_DATA", str(tmp_path))
    routines_service.reset_foreign_services()
    yield
    routines_service.reset_foreign_services()


@pytest.fixture
def client():
    app = FastAPI()
    app.state.ollama = FakeOllama()
    app.include_router(routines_router)
    with TestClient(app) as c:
        yield c, app


# === deadline_digest (service-level, direct fakes) ===

def test_deadline_digest_merges_and_sorts(monkeypatch: pytest.MonkeyPatch):
    apps = FakeAppsService([
        fake_application("a1", "Stanford MS CS", "Stanford", "2026-08-10"),
    ])
    courses = FakeCoursesService([
        fake_assignment("s1", "Problem Set 3", "2026-08-05", "c1"),
    ])
    monkeypatch.setattr(routines_service, "_get_applications_service", lambda: apps)
    monkeypatch.setattr(routines_service, "_get_courses_service", lambda: courses)

    result = routines_service.deadline_digest(days=14)

    assert [it["id"] for it in result["items"]] == ["s1", "a1"]  # sorted ascending by due
    assert result["items"][0]["kind"] == "assignment"
    assert result["items"][1]["kind"] == "application"
    assert "2 item(s)" in result["summary"]


def test_deadline_digest_both_sources_raise_gives_empty_benign_summary(monkeypatch: pytest.MonkeyPatch):
    raising = RaisingService()
    monkeypatch.setattr(routines_service, "_get_applications_service", lambda: raising)
    monkeypatch.setattr(routines_service, "_get_courses_service", lambda: raising)

    result = routines_service.deadline_digest(days=14)

    assert result["items"] == []
    assert "No deadlines" in result["summary"]


def test_deadline_digest_missing_module_is_skipped(monkeypatch: pytest.MonkeyPatch):
    def _raise_import():
        raise ModuleNotFoundError("no backend.services.applications")

    courses = FakeCoursesService([fake_assignment("s1", "Essay draft", "2026-08-01", "c1")])
    monkeypatch.setattr(routines_service, "_get_applications_service", _raise_import)
    monkeypatch.setattr(routines_service, "_get_courses_service", lambda: courses)

    result = routines_service.deadline_digest(days=14)

    assert len(result["items"]) == 1
    assert result["items"][0]["id"] == "s1"


# === essay_feedback / deadline_digest_llm (service-level, fake ollama) ===

@pytest.mark.asyncio
async def test_essay_feedback_with_fake_ollama():
    ollama = FakeOllama(content="1. Tighten the opening.", model="fake-model")
    result = await routines_service.essay_feedback(ollama, text="My essay text.", prompt_hint="Why us?")

    assert result == {"feedback": "1. Tighten the opening.", "model": "fake-model"}
    assert len(ollama.calls) == 1
    sent = ollama.calls[0]
    assert sent[0].role == "system"
    assert "coach" in sent[0].content.lower()
    assert "Why us?" in sent[1].content
    assert "My essay text." in sent[1].content


@pytest.mark.asyncio
async def test_deadline_digest_llm_with_fake_ollama(monkeypatch: pytest.MonkeyPatch):
    apps = FakeAppsService([fake_application("a1", "Fulbright", "", "2026-08-10")])
    courses = FakeCoursesService([])
    monkeypatch.setattr(routines_service, "_get_applications_service", lambda: apps)
    monkeypatch.setattr(routines_service, "_get_courses_service", lambda: courses)

    ollama = FakeOllama(content="You've got this — one deadline coming up.", model="fake-model")
    result = await routines_service.deadline_digest_llm(ollama, days=14)

    assert result["items"][0]["id"] == "a1"
    assert result["briefing"] == "You've got this — one deadline coming up."
    assert result["model"] == "fake-model"
    assert "summary" in result


# === API: catalog ===

def test_catalog_lists_both_routines(client):
    c, _app = client
    r = c.get("/api/routines/catalog")
    assert r.status_code == 200
    body = r.json()
    ids = {routine["id"] for routine in body["routines"]}
    assert ids == {"deadline-watcher", "essay-feedback"}
    for routine in body["routines"]:
        assert routine["kind"] == "on_demand"
        assert routine["name"]
        assert routine["description"]


# === API: deadline-digest (no LLM) ===

def test_get_deadline_digest_endpoint(client, monkeypatch: pytest.MonkeyPatch):
    c, _app = client
    apps = FakeAppsService([fake_application("a1", "MIT", "MIT", "2026-08-01")])
    courses = FakeCoursesService([])
    monkeypatch.setattr(routines_service, "_get_applications_service", lambda: apps)
    monkeypatch.setattr(routines_service, "_get_courses_service", lambda: courses)

    r = c.get("/api/routines/deadline-digest?days=30")
    assert r.status_code == 200
    body = r.json()
    assert len(body["items"]) == 1
    assert body["items"][0]["title"] == "MIT"


# === API: deadline-digest/brief ===

def test_post_deadline_digest_brief_ok(client, monkeypatch: pytest.MonkeyPatch):
    c, _app = client
    monkeypatch.setattr(routines_service, "_get_applications_service", lambda: FakeAppsService([]))
    monkeypatch.setattr(routines_service, "_get_courses_service", lambda: FakeCoursesService([]))

    r = c.post("/api/routines/deadline-digest/brief", json={"days": 7})
    assert r.status_code == 200
    body = r.json()
    assert body["briefing"] == "looks good"


def test_post_deadline_digest_brief_503_when_ollama_fails(client, monkeypatch: pytest.MonkeyPatch):
    c, app = client
    app.state.ollama = FakeOllama(fail=True)
    monkeypatch.setattr(routines_service, "_get_applications_service", lambda: FakeAppsService([]))
    monkeypatch.setattr(routines_service, "_get_courses_service", lambda: FakeCoursesService([]))

    r = c.post("/api/routines/deadline-digest/brief", json={})
    assert r.status_code == 503


# === API: essay-feedback ===

def test_post_essay_feedback_ok(client):
    c, _app = client
    r = c.post("/api/routines/essay-feedback", json={"text": "My essay draft."})
    assert r.status_code == 200
    body = r.json()
    assert body["feedback"] == "looks good"
    assert body["model"] == "fake-model"


def test_post_essay_feedback_422_on_empty_text(client):
    c, _app = client
    r = c.post("/api/routines/essay-feedback", json={"text": ""})
    assert r.status_code == 422


def test_post_essay_feedback_422_on_missing_text(client):
    c, _app = client
    r = c.post("/api/routines/essay-feedback", json={})
    assert r.status_code == 422


def test_post_essay_feedback_503_when_ollama_fails(client):
    c, app = client
    app.state.ollama = FakeOllama(fail=True)
    r = c.post("/api/routines/essay-feedback", json={"text": "My essay draft."})
    assert r.status_code == 503
