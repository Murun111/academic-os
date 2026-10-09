"""syllabus_ai: LLM mocked via learning_ai._hub_chat."""
import asyncio
import json

import pytest

from backend.services import syllabus_ai
from backend.services.syllabus_ai import (
    LearningAIBadOutput, LearningAIUnavailable, chunk_text, extract_syllabus)

TEXT = """BIO 101 Introductory Biology
Midterm Exam: Sept 14 (20% of grade)
Lab report due 10/3 worth 10 points
Essay 1 due Friday of week 3
Final Exam: date TBA, 30%
"""


def _patch(monkeypatch, replies):
    calls = {"n": 0}
    seq = list(replies) if isinstance(replies, list) else None

    async def fake(messages):
        calls["n"] += 1
        r = seq.pop(0) if seq else replies
        if isinstance(r, Exception):
            raise r
        return r
    monkeypatch.setattr("backend.services.learning_ai._hub_chat", fake)
    return calls


def run(**kw):
    return asyncio.run(extract_syllabus(TEXT, **kw))


def item(title, src, **kw):
    return {"title": title, "kind": "exam", "due": None, "weight": None,
            "points": None, "source_line": src, **kw}


def test_normal_json(monkeypatch):
    _patch(monkeypatch, json.dumps({
        "course_name": "BIO 101",
        "items": [
            item("Midterm Exam", "Midterm Exam: Sept 14 (20% of grade)", due="Sept 14", weight=20),
            item("Lab report", "Lab report due 10/3 worth 10 points", kind="assignment", due="10/3", points="10"),
            item("Final Exam", "Final Exam: date TBA, 30%", weight=30, kind="bogus"),
        ],
        "grading": [{"category": "Exams", "weight": 50}],
    }))
    out = run(term_year=2026)
    by = {i["title"]: i for i in out["items"]}
    assert out["course_name"] == "BIO 101"
    assert by["Midterm Exam"]["due"] == "2026-09-14" and by["Midterm Exam"]["weight"] == 20.0
    assert by["Lab report"]["due"] == "2026-10-03" and by["Lab report"]["points"] == 10.0
    assert by["Final Exam"]["due"] is None and by["Final Exam"]["kind"] == "other"
    assert out["grading"] == [{"category": "Exams", "weight": 50.0}]
    assert out["warnings"] == []


def test_chunk_merge_and_dedupe(monkeypatch):
    long_text = ("filler line about policies\n" * 400) + TEXT
    assert len(chunk_text(long_text)) > 1
    a = json.dumps({"items": [item("Midterm Exam", "Midterm Exam: Sept 14", due="2026-09-14")]})
    b = json.dumps({"items": [item("midterm exam", "Midterm Exam: Sept 14", due="2026-09-14", weight=20)],
                    "course_name": "BIO 101"})
    calls = {"n": 0}
    replies = iter([a, b, json.dumps({"items": []}), json.dumps({"items": []})])

    async def fake(messages):
        calls["n"] += 1
        return next(replies)
    monkeypatch.setattr("backend.services.learning_ai._hub_chat", fake)
    out = asyncio.run(extract_syllabus(long_text))
    assert calls["n"] == len(chunk_text(long_text))
    assert len(out["items"]) == 1
    assert out["items"][0]["weight"] == 20.0
    assert out["course_name"] == "BIO 101"


def test_hallucinated_item_dropped(monkeypatch):
    _patch(monkeypatch, json.dumps({"items": [
        item("Midterm Exam", "midterm exam: sept 14 (20% of grade)"),  # case-insensitive ok
        item("Pop Quiz", "Pop quiz every Monday worth 5%", kind="quiz"),  # invented
        item("No source", ""),
    ]}))
    out = run()
    assert [i["title"] for i in out["items"]] == ["Midterm Exam"]
    assert any("Dropped 2" in w for w in out["warnings"])


def test_relative_date_resolution(monkeypatch):
    reply = json.dumps({"items": [
        item("Essay 1", "Essay 1 due Friday of week 3", kind="assignment", due="Friday of week 3"),
        item("Midterm Exam", "Midterm Exam: Sept 14 (20% of grade)", due="Sept 14"),
        item("Lab report", "Lab report due 10/3 worth 10 points", due="not a date"),
    ]})
    _patch(monkeypatch, reply)
    out = run(term_start="2026-09-01")  # Tuesday; week 1 = Mon Aug 31
    by = {i["title"]: i for i in out["items"]}
    assert by["Essay 1"]["due"] == "2026-09-18"  # Friday of week 3
    assert by["Midterm Exam"]["due"] == "2026-09-14"  # year from term_start
    assert by["Lab report"]["due"] is None
    assert any("could not be resolved" in w for w in out["warnings"])

    # relative dates are NOT resolved without term_start
    _patch(monkeypatch, reply)
    out = run(term_year=2026)
    by = {i["title"]: i for i in out["items"]}
    assert by["Essay 1"]["due"] is None
    assert by["Midterm Exam"]["due"] == "2026-09-14"
    assert any("term start" in w for w in out["warnings"])


def test_unparseable_output_raises_bad_output(monkeypatch):
    calls = _patch(monkeypatch, "sorry, no JSON here")
    with pytest.raises(LearningAIBadOutput):
        run()
    assert calls["n"] == 2  # one retry


def test_no_model_raises_unavailable(monkeypatch):
    _patch(monkeypatch, None)
    with pytest.raises(LearningAIUnavailable):
        run()
    _patch(monkeypatch, RuntimeError("boom"))
    with pytest.raises(LearningAIUnavailable):
        run()


def test_reuses_learning_ai_exceptions():
    from backend.services import learning_ai
    assert syllabus_ai.LearningAIBadOutput is learning_ai.LearningAIBadOutput
    assert syllabus_ai.LearningAIUnavailable is learning_ai.LearningAIUnavailable


@pytest.mark.parametrize("raw,expected", [
    ("Sept 14", "2026-09-14"), ("Tue 9/15", "2026-09-15"), ("Thu, 10/3", "2026-10-03"),
    ("Week 3 (Sept 14)", "2026-09-14"), ("Session 4, Oct 20", "2026-10-20"),
    ("Friday, Oct 3", "2026-10-03"), ("14 Sept", "2026-09-14"),
])
def test_to_date_weekday_and_label_prefixes(raw, expected):
    from datetime import date
    assert syllabus_ai._to_date(raw, None, 2026).isoformat() == expected
    assert syllabus_ai._to_date(raw, date(2026, 9, 1), 2026).isoformat() == expected


def test_year_inferred_from_text_without_term(monkeypatch):
    text = "Fall 2027 BIO 101\nMidterm Exam: Sept 14 (20%)\n"
    _patch(monkeypatch, json.dumps({"items": [
        item("Midterm Exam", "Midterm Exam: Sept 14 (20%)", due="Sept 14")]}))
    out = asyncio.run(extract_syllabus(text))
    assert out["items"][0]["due"] == "2027-09-14"
    assert not out["warnings"]


def test_year_falls_back_to_current_with_warning(monkeypatch):
    from datetime import date
    text = "BIO 101\nMidterm Exam: Sept 14 (20%)\n"
    _patch(monkeypatch, json.dumps({"items": [
        item("Midterm Exam", "Midterm Exam: Sept 14 (20%)", due="Sept 14")]}))
    out = asyncio.run(extract_syllabus(text))
    assert out["items"][0]["due"] == f"{date.today().year}-09-14"
    assert any("term year" in w for w in out["warnings"])


def test_week_reference_computed_in_code_not_trusted_from_model(monkeypatch):
    text = "Midterm Exam due Thursday of Week 6\n"
    _patch(monkeypatch, json.dumps({"items": [
        item("Midterm Exam", "Midterm Exam due Thursday of Week 6", due="2026-10-02")]}))
    out = asyncio.run(extract_syllabus(text, term_start="2026-09-01"))
    assert out["items"][0]["due"] == "2026-10-08"


def test_repeated_undated_items_not_collapsed(monkeypatch):
    text = "Reading reflection week 1\nReading reflection week 2\n"
    _patch(monkeypatch, json.dumps({"items": [
        item("Reading reflection", "Reading reflection week 1"),
        item("Reading reflection", "Reading reflection week 2")]}))
    out = asyncio.run(extract_syllabus(text, term_year=2026))
    assert len(out["items"]) == 2
