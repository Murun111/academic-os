"""Tests for course credits/archive and application archive."""
from __future__ import annotations

from datetime import date, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.routers.applications import reset_service as reset_apps, router as apps_router
from backend.routers.courses import reset_service as reset_courses, router as courses_router


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("ACADEMIC_OS_DATA", str(tmp_path))
    reset_apps()
    reset_courses()
    app = FastAPI()
    app.include_router(apps_router)
    app.include_router(courses_router)
    with TestClient(app) as c:
        yield c
    reset_apps()
    reset_courses()


def _add_course(client, name="Algorithms", term="Fall 2026"):
    r = client.post("/api/courses", json={"name": name, "term": term})
    assert r.status_code == 200
    return r.json()["course"]


def _add_application(client, name="MIT", **overrides):
    body = {"name": name, "type": "undergrad"}
    body.update(overrides)
    r = client.post("/api/applications", json=body)
    assert r.status_code == 200
    return r.json()["item"]


# === course credits ===


def test_course_credits_default_none_and_patchable(client):
    c = _add_course(client)
    assert c["credits"] is None
    r = client.patch(f"/api/courses/{c['id']}", json={"credits": 4})
    assert r.status_code == 200
    assert r.json()["course"]["credits"] == 4


def test_course_credits_clearable_and_bounded(client):
    c = _add_course(client)
    client.patch(f"/api/courses/{c['id']}", json={"credits": 3})
    r = client.patch(f"/api/courses/{c['id']}", json={"credits": None})
    assert r.json()["course"]["credits"] is None
    r = client.patch(f"/api/courses/{c['id']}", json={"credits": 99})
    assert r.status_code == 422


# === course archive ===


def test_course_archive_roundtrip(client):
    c = _add_course(client)
    r = client.patch(f"/api/courses/{c['id']}", json={"archived": True})
    assert r.json()["course"]["archived"] is True
    r = client.patch(f"/api/courses/{c['id']}", json={"archived": False})
    assert r.json()["course"]["archived"] is False


def test_archived_course_assignments_leave_due_soon(client):
    c = _add_course(client)
    due = (date.today() + timedelta(days=3)).isoformat()
    r = client.post(
        "/api/courses/assignments",
        json={"course_id": c["id"], "title": "Final project", "due": due},
    )
    assert r.status_code == 200

    summary = client.get("/api/courses/summary").json()
    assert len(summary["due_soon"]) == 1

    client.patch(f"/api/courses/{c['id']}", json={"archived": True})
    summary = client.get("/api/courses/summary").json()
    assert summary["due_soon"] == []


# === application archive ===


def test_application_archive_roundtrip(client):
    a = _add_application(client)
    assert a["archived"] is False
    r = client.patch(f"/api/applications/{a['id']}", json={"archived": True})
    assert r.status_code == 200
    assert r.json()["item"]["archived"] is True
    # still listed (frontend filters), still exportable
    items = client.get("/api/applications").json()["items"]
    assert items[0]["archived"] is True


def test_archived_application_leaves_upcoming_deadlines(client):
    deadline = (date.today() + timedelta(days=5)).isoformat()
    a = _add_application(client, deadline=deadline)
    r = client.get("/api/applications/deadlines")
    assert r.status_code == 200
    assert len(r.json()["items"]) == 1

    client.patch(f"/api/applications/{a['id']}", json={"archived": True})
    assert client.get("/api/applications/deadlines").json()["items"] == []


# === secondaries status (med/dental application cycle) ===


def test_secondaries_status_between_submitted_and_interview(client):
    from backend.services.applications import STATUSES

    i = STATUSES.index
    assert i("submitted") < i("secondaries") < i("interview")

    a = _add_application(client, status="submitted")
    r = client.patch(f"/api/applications/{a['id']}", json={"status": "secondaries"})
    assert r.status_code == 200
    assert r.json()["item"]["status"] == "secondaries"


def test_secondaries_apps_still_count_toward_deadlines(client):
    from datetime import date, timedelta

    deadline = (date.today() + timedelta(days=5)).isoformat()
    _add_application(client, deadline=deadline, status="secondaries")
    items = client.get("/api/applications/deadlines").json()["items"]
    assert len(items) == 1
