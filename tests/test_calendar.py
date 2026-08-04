"""Tests for backend.services.calendar — Apple CalDAV client for Panel B.

The tests are unit-level: we mock the caldav.DAVClient to avoid hitting
the real iCloud CalDAV server (which depends on credentials that may
expire). The integration test (test_live_apple_caldav) is skipped by
default and runs only if CALDAV_LIVE_TEST=1 is set.
"""
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from backend.services.calendar import (
    AppleCalendarService,
    Calendar,
    CalendarEvent,
    CalendarServiceError,
)


# === Mock fixtures ===

def _fake_calendar(name="Work", events=None, url="https://caldav.icloud.com/cal/abc/"):
    """Build a mock caldav.Calendar that returns Event-like objects on search()."""
    cal = MagicMock()
    cal.name = name
    cal.url = url
    # events is a list of iCal byte strings (what caldav returns internally)
    # Wrap each in a real-ish caldav.Event so icalendar_instance works.
    from caldav import Event as CalEvent
    wrapped = []
    for raw_bytes in (events or []):
        ev = CalEvent()
        ev.data = raw_bytes
        wrapped.append(ev)
    cal.search.return_value = wrapped
    return cal


def _vevent(summary, start, end, location="", description=""):
    """Build a minimal VCALENDAR-wrapped VEVENT as bytes (what caldav.Event.data is)."""
    from icalendar import Calendar as ICal, Event
    cal = ICal()
    cal.add("prodid", "-//test//test//EN")
    cal.add("version", "2.0")
    event = Event()
    event.add("summary", summary)
    event.add("dtstart", start)
    event.add("dtend", end)
    if location:
        event.add("location", location)
    if description:
        event.add("description", description)
    event.add("uid", f"uid-{summary}@test")
    event.add("dtstamp", datetime.now(timezone.utc))
    cal.add_component(event)
    return cal.to_ical()


# === Service construction ===

def test_constructs_with_email_and_password(monkeypatch):
    monkeypatch.setenv("APPLE_ICLOUD_EMAIL", "x@me.com")
    monkeypatch.setenv("APPLE_CALDAV_PASSWORD", "abcd-efgh-ijkl-mnop")
    svc = AppleCalendarService()
    assert svc.email == "x@me.com"
    assert svc.password == "abcd-efgh-ijkl-mnop"


def test_raises_if_env_missing(monkeypatch, tmp_path):
    """When neither process env nor a .env file has the creds, raise."""
    monkeypatch.delenv("APPLE_ICLOUD_EMAIL", raising=False)
    monkeypatch.delenv("APPLE_CALDAV_PASSWORD", raising=False)
    # Point the service at a non-existent .env file so it doesn't pick
    # up the real credentials from the dev environment.
    import backend.services.calendar as cal_mod
    monkeypatch.setattr(cal_mod, "_ENV_PATH", tmp_path / "nonexistent.env")
    with pytest.raises(CalendarServiceError, match="APPLE_ICLOUD_EMAIL"):
        AppleCalendarService()


def test_uses_explicit_creds_over_env(monkeypatch):
    monkeypatch.setenv("APPLE_ICLOUD_EMAIL", "env@me.com")
    svc = AppleCalendarService(email="explicit@me.com", password="xyz")
    assert svc.email == "explicit@me.com"


# === list_calendars ===

def test_list_calendars_returns_calendar_summaries():
    with patch("backend.services.calendar.caldav.DAVClient") as MockClient:
        client = MagicMock()
        principal = MagicMock()
        principal.calendars.return_value = [
            _fake_calendar(name="Work", url="https://caldav.icloud.com/cal/1/"),
            _fake_calendar(name="Personal", url="https://caldav.icloud.com/cal/2/"),
        ]
        client.principal.return_value = principal
        MockClient.return_value = client

        svc = AppleCalendarService(email="x@me.com", password="y")
        cals = svc.list_calendars()

    assert len(cals) == 2
    assert cals[0].name == "Work"
    assert cals[0].url == "https://caldav.icloud.com/cal/1/"
    assert cals[1].name == "Personal"


# === list_events (date range) ===

def test_list_events_parses_vevent_into_dataclass():
    now = datetime.now(timezone.utc)
    end = now + timedelta(hours=1)
    events_data = [
        _vevent("Standup", now, end, location="Zoom"),
        _vevent("Lunch", now + timedelta(hours=2), now + timedelta(hours=3)),
    ]
    with patch("backend.services.calendar.caldav.DAVClient") as MockClient:
        client = MagicMock()
        principal = MagicMock()
        cal = _fake_calendar(name="Work", events=events_data)
        principal.calendars.return_value = [cal]
        client.principal.return_value = principal
        MockClient.return_value = client

        svc = AppleCalendarService(email="x@me.com", password="y")
        events = svc.list_events(
            start=now - timedelta(days=1),
            end=now + timedelta(days=1),
        )

    assert len(events) == 2
    e = events[0]
    assert e.summary == "Standup"
    assert e.location == "Zoom"
    # icalendar drops microsecond precision, so compare to the second
    assert e.start.replace(microsecond=0) == now.replace(microsecond=0)
    assert e.end.replace(microsecond=0) == end.replace(microsecond=0)


def test_list_events_handles_missing_optional_fields():
    now = datetime.now(timezone.utc)
    end = now + timedelta(hours=1)
    events_data = [_vevent("Quick call", now, end)]  # no location/description
    with patch("backend.services.calendar.caldav.DAVClient") as MockClient:
        client = MagicMock()
        principal = MagicMock()
        principal.calendars.return_value = [_fake_calendar(events=events_data)]
        client.principal.return_value = principal
        MockClient.return_value = client

        svc = AppleCalendarService(email="x@me.com", password="y")
        events = svc.list_events(start=now, end=end + timedelta(minutes=1))
    assert len(events) == 1
    assert events[0].location == ""
    assert events[0].description == ""


def test_list_events_filters_by_calendar_name():
    now = datetime.now(timezone.utc)
    end = now + timedelta(hours=1)
    events_data = [_vevent("Work event", now, end)]
    with patch("backend.services.calendar.caldav.DAVClient") as MockClient:
        client = MagicMock()
        principal = MagicMock()
        principal.calendars.return_value = [
            _fake_calendar(name="Work", events=events_data),
            _fake_calendar(name="Personal", events=[]),
        ]
        client.principal.return_value = principal
        MockClient.return_value = client

        svc = AppleCalendarService(email="x@me.com", password="y")
        work_only = svc.list_events(
            start=now, end=end + timedelta(minutes=1), calendar_name="Work"
        )
        empty = svc.list_events(
            start=now, end=end + timedelta(minutes=1), calendar_name="Personal"
        )
    assert len(work_only) == 1
    assert len(empty) == 0


def test_list_events_sorts_chronologically():
    now = datetime.now(timezone.utc)
    events_data = [
        _vevent("Later", now + timedelta(hours=3), now + timedelta(hours=4)),
        _vevent("Earlier", now + timedelta(hours=1), now + timedelta(hours=2)),
    ]
    with patch("backend.services.calendar.caldav.DAVClient") as MockClient:
        client = MagicMock()
        principal = MagicMock()
        principal.calendars.return_value = [_fake_calendar(events=events_data)]
        client.principal.return_value = principal
        MockClient.return_value = client

        svc = AppleCalendarService(email="x@me.com", password="y")
        events = svc.list_events(start=now, end=now + timedelta(days=1))
    assert [e.summary for e in events] == ["Earlier", "Later"]


# === Auth failure handling ===

def test_auth_failure_raises_helpful_error():
    with patch("backend.services.calendar.caldav.DAVClient") as MockClient:
        import caldav.lib.error as caldav_error
        client = MagicMock()
        client.principal.side_effect = caldav_error.AuthorizationError(
            url="https://caldav.icloud.com", reason="Unauthorized"
        )
        MockClient.return_value = client

        svc = AppleCalendarService(email="x@me.com", password="wrong")
        with pytest.raises(CalendarServiceError, match="auth failed"):
            svc.list_calendars()


# === Live integration test (skipped unless CALDAV_LIVE_TEST=1) ===

@pytest.mark.skipif(
    not os.environ.get("CALDAV_LIVE_TEST"),
    reason="live CalDAV test — set CALDAV_LIVE_TEST=1 to enable",
)
def test_live_apple_caldav(tmp_path: Path):
    """Live test against the real Apple CalDAV. Run with: CALDAV_LIVE_TEST=1 pytest ..."""
    import caldav  # noqa
    email = os.environ.get("APPLE_ICLOUD_EMAIL") or AppleCalendarService._env_email()
    password = os.environ.get("APPLE_CALDAV_PASSWORD") or AppleCalendarService._env_password()
    if not email or not password:
        pytest.skip("APPLE_ICLOUD_EMAIL / APPLE_CALDAV_PASSWORD not set")
    svc = AppleCalendarService(email=email, password=password)
    cals = svc.list_calendars()
    assert len(cals) > 0, "no calendars found"
    print(f"\nLive: {len(cals)} calendars — {[c.name for c in cals]}")
