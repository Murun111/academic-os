"""Syllabus import endpoints: /api/courses/syllabus/{preview,apply}."""
from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.routers.courses import reset_service, router

TEXT = """BIO 101 Introductory Biology
Midterm Exam: Sept 14 (20% of grade)
Lab report due 10/3 worth 10 points
"""

REPLY = json.dumps({
    "course_name": "BIO 101",
    "items": [
        {"title": "Midterm Exam", "kind": "exam", "due": "Sept 14", "weight": 20,
         "points": None, "source_line": "Midterm Exam: Sept 14 (20% of grade)"},
    ],
    "grading": [],
})


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("ACADEMIC_OS_DATA", str(tmp_path))
    reset_service()
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as c:
        yield c
    reset_service()


def _llm(monkeypatch, reply):
    async def fake(messages):
        if isinstance(reply, Exception):
            raise reply
        return reply
    monkeypatch.setattr("backend.services.learning_ai._hub_chat", fake)


def test_preview_file(client, monkeypatch):
    _llm(monkeypatch, REPLY)
    r = client.post(
        "/api/courses/syllabus/preview",
        files={"file": ("syl.txt", TEXT.encode(), "text/plain")},
        data={"term_year": "2026"},
    )
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["items"][0]["due"] == "2026-09-14"
    assert j["text_chars"] == len(TEXT.strip())
    assert client.get("/api/courses").json()["count"] == 0  # saves nothing


def test_preview_text_field(client, monkeypatch):
    _llm(monkeypatch, REPLY)
    r = client.post("/api/courses/syllabus/preview", data={"text": TEXT, "term_year": "2026"})
    assert r.status_code == 200 and r.json()["course_name"] == "BIO 101"


def test_preview_unsupported_415(client):
    r = client.post("/api/courses/syllabus/preview", files={"file": ("a.exe", b"zz")})
    assert r.status_code == 415


def test_preview_empty_422(client):
    r = client.post("/api/courses/syllabus/preview", files={"file": ("a.txt", b"   \n")})
    assert r.status_code == 422 and "readable text" in r.json()["detail"]
    assert client.post("/api/courses/syllabus/preview").status_code == 422


def test_preview_too_large_413(client, monkeypatch):
    monkeypatch.setattr("backend.routers.courses.MAX_INPUT_BYTES", 10)
    r = client.post("/api/courses/syllabus/preview", files={"file": ("a.txt", b"x" * 11)})
    assert r.status_code == 413


def test_preview_503_and_502(client, monkeypatch):
    from backend.services.learning_ai import LearningAIUnavailable
    _llm(monkeypatch, LearningAIUnavailable("no model"))
    assert client.post("/api/courses/syllabus/preview", data={"text": TEXT}).status_code == 503
    _llm(monkeypatch, "not json at all")
    assert client.post("/api/courses/syllabus/preview", data={"text": TEXT}).status_code == 502


ITEMS = [
    {"title": "Midterm Exam", "due": "2026-09-14", "weight": 20, "kind": "exam"},
    {"title": "Lab report", "due": None, "weight": None, "kind": "assignment"},
]


def test_apply_new_course(client):
    r = client.post("/api/courses/syllabus/apply",
                    json={"new_course": {"name": "BIO 101", "term": "Fall 2026"}, "items": ITEMS})
    assert r.status_code == 200, r.text
    j = r.json()
    assert (j["created"], j["skipped"]) == (2, 0)
    a = client.get("/api/courses/assignments", params={"course_id": j["course"]["id"]}).json()
    by = {x["title"]: x for x in a["assignments"]}
    assert by["Midterm Exam"]["weight"] == pytest.approx(0.2)
    assert by["Midterm Exam"]["due"] == "2026-09-14"


def test_apply_existing_skips_duplicates(client):
    c = client.post("/api/courses", json={"name": "BIO", "term": "F26"}).json()["course"]
    client.post("/api/courses/assignments",
                json={"course_id": c["id"], "title": "midterm  exam", "due": "2026-09-14"})
    items = ITEMS + [dict(ITEMS[0])]  # in-batch duplicate too
    r = client.post("/api/courses/syllabus/apply", json={"course_id": c["id"], "items": items})
    assert r.status_code == 200
    assert (r.json()["created"], r.json()["skipped"]) == (1, 2)


@pytest.mark.parametrize("payload,code", [
    ({"items": ITEMS}, 422),
    ({"course_id": "nope", "items": ITEMS}, 404),
    ({"new_course": {"name": "A", "term": "B"}, "items": [{"title": "  ", "due": None}]}, 422),
    ({"new_course": {"name": "A", "term": "B"}, "items": [{"title": "x", "due": "Sept 1"}]}, 422),
    ({"new_course": {"name": "A", "term": ""}, "items": [{"title": "x"}]}, 422),
])
def test_apply_validation(client, payload, code):
    r = client.post("/api/courses/syllabus/apply", json=payload)
    assert r.status_code == code
    assert client.get("/api/courses").json()["count"] == 0  # nothing created on rejection


def test_apply_out_of_range_weight_is_dropped_with_warning(client):
    # Was a whole-batch 422; point-based syllabi put points in weight (e.g. 150).
    r = client.post("/api/courses/syllabus/apply", json={
        "new_course": {"name": "CALC", "term": "F26"},
        "items": [{"title": "Midterm", "due": "2026-10-20", "weight": 150, "points": 100},
                  {"title": "Quiz", "due": "2026-10-21", "weight": 5}]})
    assert r.status_code == 200
    assert r.json()["created"] == 2 and len(r.json()["warnings"]) == 1
    cid = r.json()["course"]["id"]
    a = {x["title"]: x for x in client.get(f"/api/courses/assignments?course_id={cid}").json()["assignments"]}
    assert a["Midterm"]["weight"] is None and "100 pts" in a["Midterm"]["notes"]
    assert a["Quiz"]["weight"] == 0.05


def test_apply_repeated_undated_items_all_land_and_reimport_skips(client):
    c = client.post("/api/courses", json={"name": "BIO", "term": "F26"}).json()["course"]
    items = [{"title": "Reading reflection"}] * 3
    r = client.post("/api/courses/syllabus/apply", json={"course_id": c["id"], "items": items})
    assert (r.json()["created"], r.json()["skipped"]) == (3, 0)
    r = client.post("/api/courses/syllabus/apply", json={"course_id": c["id"], "items": items})
    assert (r.json()["created"], r.json()["skipped"]) == (0, 3)


def test_preview_pasted_text_over_cap_is_413(client):
    r = client.post("/api/courses/syllabus/preview", data={"text": "x" * 200_001})
    assert r.status_code == 413
