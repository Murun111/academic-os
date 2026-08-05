"""Tests for the daily deadline reminder (macOS notification)."""
import json
from datetime import date, timedelta

import pytest

from backend.services import deadline_reminders
from backend.services.applications import ApplicationsService
from backend.services.routines import reset_foreign_services


@pytest.fixture
def data_root(monkeypatch, tmp_path):
    monkeypatch.setenv("ACADEMIC_OS_DATA", str(tmp_path))
    reset_foreign_services()
    yield tmp_path
    reset_foreign_services()


@pytest.fixture
def sent(monkeypatch):
    """Capture notify() calls instead of firing osascript."""
    calls = []
    monkeypatch.setattr(deadline_reminders, "notify", lambda title, body: calls.append((title, body)))
    return calls


def _seed_app(tmp_path, days_ahead=3):
    svc = ApplicationsService(data_dir=tmp_path / "data" / "applications")
    deadline = (date.today() + timedelta(days=days_ahead)).isoformat()
    svc.add(name="Stanford", type="undergrad", deadline=deadline)
    return deadline


def test_build_summary_none_when_nothing_due(data_root):
    assert deadline_reminders.build_summary() is None


def test_build_summary_single_item(data_root):
    deadline = _seed_app(data_root)
    title, message = deadline_reminders.build_summary()
    assert title == "1 deadline in the next 7 days"
    assert "Stanford" in message and deadline in message


def test_check_and_send_once_per_day(data_root, sent):
    _seed_app(data_root)
    first = deadline_reminders.check_and_send()
    assert first["sent"] is True
    assert len(sent) == 1
    second = deadline_reminders.check_and_send()
    assert second == {"sent": False, "reason": "already_sent_today"}
    assert len(sent) == 1  # no second notification


def test_check_and_send_respects_toggle(data_root, sent):
    _seed_app(data_root)
    (data_root / "data").mkdir(exist_ok=True)
    (data_root / "data" / "profile.json").write_text(
        json.dumps({"stage": "highschool", "reminders": False})
    )
    assert deadline_reminders.check_and_send() == {"sent": False, "reason": "disabled"}
    assert sent == []
    # force (the Settings test button) ignores the toggle
    forced = deadline_reminders.check_and_send(force=True)
    assert forced["sent"] is True
    assert len(sent) == 1
    # a forced send never consumes the daily slot
    assert not (data_root / "data" / "notify_state.json").exists()


def test_nothing_due_marks_day_done(data_root, sent):
    result = deadline_reminders.check_and_send()
    assert result == {"sent": False, "reason": "nothing_due"}
    state = json.loads((data_root / "data" / "notify_state.json").read_text())
    assert state["last_sent"] == date.today().isoformat()
    assert sent == []
