"""Tests for the Courses & Assignments module (/api/courses/*)."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.routers.courses import reset_service, router


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("ACADEMIC_OS_DATA", str(tmp_path))
    reset_service()
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as c:
        yield c
    reset_service()


def _add_course(client, name="Algorithms", term="Fall 2026", instructor="Dr. Knuth"):
    r = client.post(
        "/api/courses", json={"name": name, "term": term, "instructor": instructor}
    )
    assert r.status_code == 200
    return r.json()["course"]


def _add_assignment(client, course_id, **overrides):
    body = {"course_id": course_id, "title": "HW1"}
    body.update(overrides)
    r = client.post("/api/courses/assignments", json=body)
    return r


# === course CRUD ===


def test_add_and_list_courses(client):
    course = _add_course(client)
    assert course["name"] == "Algorithms"
    assert course["term"] == "Fall 2026"
    assert course["instructor"] == "Dr. Knuth"
    assert course["id"]

    r = client.get("/api/courses")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 1
    assert body["courses"][0]["id"] == course["id"]


def test_update_course(client):
    course = _add_course(client)
    r = client.patch(f"/api/courses/{course['id']}", json={"term": "Spring 2027"})
    assert r.status_code == 200
    assert r.json()["course"]["term"] == "Spring 2027"
    # unrelated fields unchanged
    assert r.json()["course"]["name"] == "Algorithms"


def test_update_missing_course_404(client):
    r = client.patch("/api/courses/does-not-exist", json={"term": "Spring 2027"})
    assert r.status_code == 404


def test_delete_course(client):
    course = _add_course(client)
    r = client.delete(f"/api/courses/{course['id']}")
    assert r.status_code == 200
    r2 = client.get("/api/courses")
    assert r2.json()["count"] == 0


def test_delete_missing_course_404(client):
    r = client.delete("/api/courses/does-not-exist")
    assert r.status_code == 404


def test_delete_course_cascades_assignments(client):
    course = _add_course(client)
    _add_assignment(client, course["id"], title="HW1")
    _add_assignment(client, course["id"], title="HW2")

    r = client.get(f"/api/courses/assignments?course_id={course['id']}")
    assert r.json()["count"] == 2

    client.delete(f"/api/courses/{course['id']}")

    r2 = client.get(f"/api/courses/assignments?course_id={course['id']}")
    assert r2.json()["count"] == 0


def test_add_course_rejects_empty_name(client):
    r = client.post("/api/courses", json={"name": "", "term": "Fall 2026"})
    assert r.status_code == 422


# === assignment CRUD ===


def test_add_assignment_to_missing_course_404(client):
    r = _add_assignment(client, "does-not-exist", title="HW1")
    assert r.status_code == 404


def test_add_and_list_assignments(client):
    course = _add_course(client)
    r = _add_assignment(client, course["id"], title="Problem Set 1", due="2026-08-15")
    assert r.status_code == 200
    assignment = r.json()["assignment"]
    assert assignment["title"] == "Problem Set 1"
    assert assignment["status"] == "todo"
    assert assignment["course_id"] == course["id"]

    r2 = client.get("/api/courses/assignments")
    assert r2.status_code == 200
    assert r2.json()["count"] == 1


def test_list_assignments_filters_by_status(client):
    course = _add_course(client)
    a1 = _add_assignment(client, course["id"], title="HW1").json()["assignment"]
    _add_assignment(client, course["id"], title="HW2")
    client.patch(f"/api/courses/assignments/{a1['id']}", json={"status": "done"})

    r = client.get(f"/api/courses/assignments?status=done")
    assert r.json()["count"] == 1
    assert r.json()["assignments"][0]["id"] == a1["id"]


def test_update_assignment_status_and_grade(client):
    course = _add_course(client)
    a = _add_assignment(client, course["id"], title="HW1").json()["assignment"]
    r = client.patch(
        f"/api/courses/assignments/{a['id']}", json={"status": "done", "grade": 92.5}
    )
    assert r.status_code == 200
    body = r.json()["assignment"]
    assert body["status"] == "done"
    assert body["grade"] == 92.5


def test_update_assignment_invalid_status_422(client):
    course = _add_course(client)
    a = _add_assignment(client, course["id"], title="HW1").json()["assignment"]
    r = client.patch(f"/api/courses/assignments/{a['id']}", json={"status": "later"})
    assert r.status_code == 422


def test_update_missing_assignment_404(client):
    r = client.patch("/api/courses/assignments/does-not-exist", json={"status": "done"})
    assert r.status_code == 404


def test_delete_assignment(client):
    course = _add_course(client)
    a = _add_assignment(client, course["id"], title="HW1").json()["assignment"]
    r = client.delete(f"/api/courses/assignments/{a['id']}")
    assert r.status_code == 200
    r2 = client.get(f"/api/courses/assignments?course_id={course['id']}")
    assert r2.json()["count"] == 0


def test_delete_missing_assignment_404(client):
    r = client.delete("/api/courses/assignments/does-not-exist")
    assert r.status_code == 404


# === grade weighting ===


def test_course_grade_weighted_average(client):
    course = _add_course(client)
    _add_assignment(client, course["id"], title="Midterm", grade=80, weight=0.3)
    _add_assignment(client, course["id"], title="Final", grade=90, weight=0.7)

    r = client.get("/api/courses/summary")
    assert r.status_code == 200
    summary = next(c for c in r.json()["courses"] if c["id"] == course["id"])
    expected = (80 * 0.3 + 90 * 0.7) / (0.3 + 0.7)
    assert summary["grade"] == pytest.approx(expected)
    assert summary["open_assignments"] == 2  # both still "todo"


def test_course_grade_none_when_ungraded(client):
    course = _add_course(client)
    _add_assignment(client, course["id"], title="HW1")

    r = client.get("/api/courses/summary")
    summary = next(c for c in r.json()["courses"] if c["id"] == course["id"])
    assert summary["grade"] is None


# === due_soon ===


def test_due_soon_excludes_done_includes_overdue_and_sorts_ascending(client):
    from datetime import date, timedelta

    course = _add_course(client)
    today = date.today()
    past = (today - timedelta(days=1)).isoformat()
    soon_later = (today + timedelta(days=10)).isoformat()
    soon_earlier = (today + timedelta(days=2)).isoformat()
    far_future = (today + timedelta(days=100)).isoformat()

    _add_assignment(client, course["id"], title="Past due", due=past)
    later = _add_assignment(
        client, course["id"], title="Later", due=soon_later
    ).json()["assignment"]
    earlier = _add_assignment(
        client, course["id"], title="Earlier", due=soon_earlier
    ).json()["assignment"]
    done_one = _add_assignment(
        client, course["id"], title="Done already", due=soon_earlier
    ).json()["assignment"]
    _add_assignment(client, course["id"], title="Too far", due=far_future)

    client.patch(f"/api/courses/assignments/{done_one['id']}", json={"status": "done"})

    r = client.get("/api/courses/summary")
    due_soon = r.json()["due_soon"]
    ids = [a["id"] for a in due_soon]

    assert earlier["id"] in ids
    assert later["id"] in ids
    assert done_one["id"] not in ids  # done excluded
    assert "Past due" in [a["title"] for a in due_soon]  # overdue todo stays visible
    assert "Too far" not in [a["title"] for a in due_soon]  # beyond 14-day horizon

    # ascending order
    due_dates = [a["due"] for a in due_soon]
    assert due_dates == sorted(due_dates)


# === bug sweep: due validation, overdue, unweighted grades ===


@pytest.mark.parametrize("bad", ["tomorrow", "2026-13-45", "10/10/2026"])
def test_invalid_due_rejected_422(client, bad):
    course = _add_course(client)
    r = _add_assignment(client, course["id"], title="X", due=bad)
    assert r.status_code == 422
    ok = _add_assignment(client, course["id"], title="Y").json()["assignment"]
    r = client.patch(f"/api/courses/assignments/{ok['id']}", json={"due": bad})
    assert r.status_code == 422
    assert client.get("/api/courses/summary").status_code == 200


def test_due_normalized_and_datetime_accepted(client):
    course = _add_course(client)
    a = _add_assignment(client, course["id"], title="DT", due="2026-10-10T09:00").json()["assignment"]
    assert a["due"] == "2026-10-10"
    a2 = _add_assignment(client, course["id"], title="Compact", due="20261011").json()["assignment"]
    assert a2["due"] == "2026-10-11"


def test_due_soon_survives_legacy_malformed_due(tmp_path):
    from datetime import date, timedelta
    from backend.services.courses import CoursesService

    svc = CoursesService(tmp_path)
    c = svc.add_course(name="C", term="T")
    good = svc.add_assignment(course_id=c.id, title="good", due=(date.today() + timedelta(days=1)).isoformat())
    # bypass validation, as a legacy/hand-edited ledger would
    items = svc._read_assignments()
    bad = svc.add_assignment(course_id=c.id, title="bad")
    items = svc._read_assignments()
    for a in items:
        if a.id == bad.id:
            a.due = "tomorrow"
    svc._write_assignments(items)
    assert [a.id for a in svc.due_soon()] == [good.id]


def test_overdue_todo_listed_done_not(tmp_path):
    from datetime import date, timedelta
    from backend.services.courses import CoursesService

    svc = CoursesService(tmp_path)
    c = svc.add_course(name="C", term="T")
    y = (date.today() - timedelta(days=1)).isoformat()
    late = svc.add_assignment(course_id=c.id, title="late", due=y)
    svc.add_assignment(course_id=c.id, title="finished", due=y, status="done")
    assert [a.id for a in svc.due_soon()] == [late.id]


def test_course_grade_unweighted_items_not_ignored(tmp_path):
    from backend.services.courses import CoursesService

    svc = CoursesService(tmp_path)
    c = svc.add_course(name="C", term="T")
    svc.add_assignment(course_id=c.id, title="Midterm", grade=80, weight=0.3)
    svc.add_assignment(course_id=c.id, title="Quiz", grade=100)
    assert svc.course_grade(c.id) == pytest.approx(90.0)
    # explicit zero weight stays zero
    svc.add_assignment(course_id=c.id, title="Extra", grade=0, weight=0)
    assert svc.course_grade(c.id) == pytest.approx(90.0)


def test_concurrent_updates_and_adds_lose_nothing(tmp_path):
    """F18: update/add racing from threads must not drop changes or 500."""
    import threading
    from backend.services.courses import CoursesService
    svc = CoursesService(tmp_path)
    c = svc.add_course(name="C", term="T")
    seeds = [svc.add_assignment(course_id=c.id, title=f"s{i}") for i in range(40)]
    errors = []

    def upd(a):
        try:
            svc.update_assignment(a.id, notes="touched")
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    def add(i):
        try:
            svc.add_assignment(course_id=c.id, title=f"n{i}")
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    ts = [threading.Thread(target=upd, args=(a,)) for a in seeds]
    ts += [threading.Thread(target=add, args=(i,)) for i in range(40)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert errors == []
    items = svc.list_assignments()
    assert len(items) == 80
    assert sum(1 for a in items if a.notes == "touched") == 40
    assert not list(tmp_path.glob("*.tmp"))
