"""Grounding: the student-context block reflects the student's real data so
local-AI chat answers from it instead of guessing. Data root is isolated by
the autouse conftest fixture, so these never touch ~/.academic-os.

Writes go through StudyService directly (not the HTTP router, whose service is
memoized at module level and would otherwise leak a prior test's data root into
this one) so every write and read hits the same current root.
"""
from __future__ import annotations

import datetime as _dt

from backend.app import _chat_system_context
from backend.services.student_context import build_context
from backend.services.study import StudyService
from backend.vault import agentic_os_dir


def _study() -> StudyService:
    return StudyService(data_dir=agentic_os_dir() / "data" / "study")


def _soon(days: int = 2) -> str:
    return (_dt.date.today() + _dt.timedelta(days=days)).isoformat()


def test_empty_root_has_no_context():
    # Fresh isolated root: no profile, no deadlines, no tasks → nothing to ground.
    assert build_context() == ""


def test_context_includes_open_task_this_week():
    _study().add(title="Finish ACT practice set", day=_soon())
    ctx = build_context()
    assert "Finish ACT practice set" in ctx
    assert "Never invent" in ctx  # framed as reference data, not an instruction


def test_done_task_is_not_grounded():
    _study().add(title="Already finished essay", day=_soon(1), done=True)
    assert "Already finished essay" not in build_context()


def test_chat_context_leads_with_house_style_and_carries_grounding():
    _study().add(title="Register for the SAT", day=_soon(3))
    msgs = _chat_system_context("what should I do this week?")
    assert msgs[0].role == "system"
    assert "Academic OS" in msgs[0].content  # house style leads
    assert "Register for the SAT" in "\n".join(m.content for m in msgs)
