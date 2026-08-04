"""Tests for the Study / Task Planner module (service + /api/study/* routes)."""
from __future__ import annotations

import sys
import types
from datetime import date, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.routers.study import reset_service, router


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("ACADEMIC_OS_DATA", str(tmp_path))
    reset_service()
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as c:
        yield c
    reset_service()


def _install_fake_module(monkeypatch, dotted_name: str, service_attr: str, factory):
    """Insert a fake module into sys.modules so `from <dotted_name> import
    <service_attr>` resolves to a stand-in class, regardless of whether the
    real module exists on disk yet (built in parallel by another agent)."""
    mod = types.ModuleType(dotted_name)
    setattr(mod, service_attr, factory)
    monkeypatch.setitem(sys.modules, dotted_name, mod)


# === CRUD ===


def test_create_and_list_task(client: TestClient):
    r = client.post("/api/study/tasks", json={"title": "Read chapter 4", "day": "2026-08-01"})
    assert r.status_code == 200
    body = r.json()
    assert body["title"] == "Read chapter 4"
    assert body["day"] == "2026-08-01"
    assert body["done"] is False
    assert body["priority"] == "normal"

    r = client.get("/api/study/tasks")
    assert r.status_code == 200
    items = r.json()
    assert len(items) == 1
    assert items[0]["title"] == "Read chapter 4"


def test_list_filters_by_day_and_done(client: TestClient):
    client.post("/api/study/tasks", json={"title": "A", "day": "2026-08-01"})
    client.post("/api/study/tasks", json={"title": "B", "day": "2026-08-02"})

    r = client.get("/api/study/tasks", params={"day": "2026-08-01"})
    assert [t["title"] for t in r.json()] == ["A"]

    r = client.get("/api/study/tasks", params={"done": False})
    assert len(r.json()) == 2

    r = client.get("/api/study/tasks", params={"done": True})
    assert r.json() == []


def test_update_task(client: TestClient):
    created = client.post("/api/study/tasks", json={"title": "Draft essay"}).json()
    r = client.patch(f"/api/study/tasks/{created['id']}", json={"title": "Draft essay v2", "priority": "high"})
    assert r.status_code == 200
    body = r.json()
    assert body["title"] == "Draft essay v2"
    assert body["priority"] == "high"


def test_delete_task(client: TestClient):
    created = client.post("/api/study/tasks", json={"title": "Temp"}).json()
    r = client.delete(f"/api/study/tasks/{created['id']}")
    assert r.status_code == 200
    assert client.get("/api/study/tasks").json() == []


def test_delete_unknown_task_returns_404(client: TestClient):
    r = client.delete("/api/study/tasks/doesnotexist")
    assert r.status_code == 404


def test_bad_input_rejected(client: TestClient):
    r = client.post("/api/study/tasks", json={"title": ""})
    assert r.status_code == 422

    r = client.post("/api/study/tasks", json={"title": "ok", "priority": "urgent"})
    assert r.status_code == 422


# === done / reopen round-trip ===


def test_done_and_reopen_round_trip(client: TestClient):
    created = client.post("/api/study/tasks", json={"title": "Study for exam"}).json()
    task_id = created["id"]

    r = client.post(f"/api/study/tasks/{task_id}/done")
    assert r.status_code == 200
    assert r.json()["done"] is True

    r = client.post(f"/api/study/tasks/{task_id}/reopen")
    assert r.status_code == 200
    assert r.json()["done"] is False


def test_done_unknown_task_returns_404(client: TestClient):
    r = client.post("/api/study/tasks/doesnotexist/done")
    assert r.status_code == 404


# === agenda ===


def test_agenda_merges_and_sorts_across_kinds(client: TestClient, monkeypatch):
    today = date.today()
    task_day = (today + timedelta(days=2)).isoformat()
    app_date = (today + timedelta(days=1)).isoformat()
    assignment_date = (today + timedelta(days=3)).isoformat()

    client.post("/api/study/tasks", json={"title": "My task", "day": task_day})

    class FakeApplicationsService:
        def __init__(self, data_dir):
            pass

        def upcoming_deadlines(self, days):
            return [
                types.SimpleNamespace(
                    id="app1", title="Apply to Foo U", date=app_date, type="application", status="open"
                )
            ]

    class FakeCoursesService:
        def __init__(self, data_dir):
            pass

        def due_soon(self, days):
            return [
                types.SimpleNamespace(
                    id="asg1", title="Problem set 3", date=assignment_date, course_id="cs101", status="pending"
                )
            ]

    _install_fake_module(monkeypatch, "backend.services.applications", "ApplicationsService", FakeApplicationsService)
    _install_fake_module(monkeypatch, "backend.services.courses", "CoursesService", FakeCoursesService)

    r = client.get("/api/study/agenda", params={"days": 7})
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 3
    dates = [item["date"] for item in body["items"]]
    assert dates == sorted(dates)
    kinds = {item["kind"] for item in body["items"]}
    assert kinds == {"task", "application", "assignment"}

    app_item = next(i for i in body["items"] if i["kind"] == "application")
    assert app_item["meta"] == {"type": "application", "status": "open"}

    asg_item = next(i for i in body["items"] if i["kind"] == "assignment")
    assert asg_item["meta"] == {"course_id": "cs101", "status": "pending"}


def test_agenda_resilient_to_foreign_service_failure(client: TestClient, monkeypatch):
    client.post("/api/study/tasks", json={"title": "Only mine", "day": date.today().isoformat()})

    class BrokenApplicationsService:
        def __init__(self, data_dir):
            pass

        def upcoming_deadlines(self, days):
            raise RuntimeError("applications service is broken")

    class BrokenCoursesService:
        def __init__(self, data_dir):
            raise RuntimeError("courses service failed to construct")

    _install_fake_module(monkeypatch, "backend.services.applications", "ApplicationsService", BrokenApplicationsService)
    _install_fake_module(monkeypatch, "backend.services.courses", "CoursesService", BrokenCoursesService)

    r = client.get("/api/study/agenda", params={"days": 7})
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 1
    assert body["items"][0]["kind"] == "task"
    assert body["items"][0]["title"] == "Only mine"


def test_agenda_excludes_tasks_outside_window(client: TestClient):
    far = (date.today() + timedelta(days=30)).isoformat()
    client.post("/api/study/tasks", json={"title": "Far away", "day": far})
    client.post("/api/study/tasks", json={"title": "No date"})

    r = client.get("/api/study/agenda", params={"days": 7})
    assert r.status_code == 200
    assert r.json()["items"] == []
