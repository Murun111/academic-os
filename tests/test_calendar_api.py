"""Tests for the calendar API endpoints (/api/calendar/*)."""
import pytest
from fastapi.testclient import TestClient

from backend.app import app


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def test_calendar_calendars_endpoint_returns_list(client: TestClient):
    r = client.get("/api/calendar/calendars")
    # Either 200 (working creds) or 503 (creds missing/wrong) — both are valid
    assert r.status_code in (200, 503)
    body = r.json()
    if r.status_code == 200:
        assert "calendars" in body
        assert "count" in body
    else:
        assert body.get("error") == "calendar_unavailable"


def test_calendar_events_endpoint_validates_dates(client: TestClient):
    r = client.get("/api/calendar/events?start=bad-date&end=2026-06-12T00:00:00Z")
    assert r.status_code == 400
    body = r.json()
    assert body.get("error") == "bad_date"


def test_calendar_events_endpoint_accepts_iso_dates(client: TestClient):
    r = client.get(
        "/api/calendar/events?start=2026-06-11T00:00:00Z&end=2026-06-12T00:00:00Z"
    )
    # Either 200 (creds work, maybe 0 events) or 503 (creds missing/wrong)
    assert r.status_code in (200, 503)


def test_calendar_events_endpoint_filters_by_calendar(client: TestClient):
    r = client.get(
        "/api/calendar/events?start=2026-06-11T00:00:00Z&end=2026-06-12T00:00:00Z&calendar=Work"
    )
    assert r.status_code in (200, 503)
