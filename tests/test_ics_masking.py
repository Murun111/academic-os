"""Feed-URL masking contract for the ICS connector.

Feed URLs embed a per-student secret token (e.g. Canvas's
`.../feeds/calendars/user_XXXX.ics?...`). Nothing that reaches the client —
service-level `masked_config()` or any /api/connectors/ics* router response —
may include the URL's path or query. Only `{id, host, configured}` per feed.
"""
from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.routers.connectors import router, reset_services
from backend.services.ics_sync import IcsSyncService

SECRET_URL = "https://canvas.school.edu/feeds/calendars/user_SUPERSECRETTOKEN99.ics?auth=abc123"
SECRET_URL_2 = "https://moodle.other.edu:8443/cal/private/user_ANOTHERSECRET.ics?token=xyz"


def _assert_no_leak(payload: dict, *secret_urls: str) -> None:
    """The serialized response must not contain any secret URL, its path,
    or its query — anywhere, at any nesting depth."""
    blob = json.dumps(payload)
    for url in secret_urls:
        assert url not in blob
        # path component (the bit after the host) must not leak either
        after_host = url.split("://", 1)[1].split("/", 1)
        if len(after_host) == 2:
            assert ("/" + after_host[1]) not in blob
    for feed in payload.get("feeds", []):
        assert set(feed.keys()) == {"id", "host", "configured"}
        assert isinstance(feed["host"], str)
        assert "/" not in feed["host"]
        assert "?" not in feed["host"]
        assert "token" not in feed["host"].lower()
        assert "secret" not in feed["host"].lower()


# ── service-level ────────────────────────────────────────────────


def test_masked_config_strips_path_and_query(tmp_path):
    svc = IcsSyncService(data_dir=tmp_path / "connectors")
    svc.add_feed(SECRET_URL)
    svc.add_feed(SECRET_URL_2)
    masked = svc.masked_config()
    _assert_no_leak(masked, SECRET_URL, SECRET_URL_2)
    assert masked["feeds"][0]["host"] == "canvas.school.edu"
    assert masked["feeds"][1]["host"] == "moodle.other.edu"
    assert masked["feeds"][0]["configured"] is True


def test_masked_config_empty_feeds(tmp_path):
    svc = IcsSyncService(data_dir=tmp_path / "connectors")
    masked = svc.masked_config()
    assert masked["feeds"] == []
    assert masked["last_sync"] is None


def test_masked_config_survives_unparseable_url(tmp_path):
    svc = IcsSyncService(data_dir=tmp_path / "connectors")
    # add_feed doesn't validate; masked_config must not blow up on garbage
    svc.add_feed("not-a-url-at-all")
    masked = svc.masked_config()
    assert masked["feeds"][0]["host"] == ""
    assert masked["feeds"][0]["configured"] is True


# ── router-level ─────────────────────────────────────────────────


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("ACADEMIC_OS_DATA", str(tmp_path))
    reset_services()
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as c:
        yield c
    reset_services()


def test_get_status_never_leaks_feed_url(client):
    client.post("/api/connectors/ics", json={"url": SECRET_URL})
    client.post("/api/connectors/ics", json={"url": SECRET_URL_2})
    r = client.get("/api/connectors/ics")
    assert r.status_code == 200
    _assert_no_leak(r.json(), SECRET_URL, SECRET_URL_2)


def test_add_feed_response_never_leaks_url(client):
    r = client.post("/api/connectors/ics", json={"url": SECRET_URL})
    assert r.status_code == 200
    _assert_no_leak(r.json(), SECRET_URL)
    # the raw response body text too, not just the parsed dict, in case of
    # an extra field the dict-shape check above wouldn't catch
    assert "SUPERSECRETTOKEN99" not in r.text
    assert "auth=abc123" not in r.text


def test_remove_feed_response_never_leaks_remaining_url(client):
    """Removing one feed must not expose the URL of any feed left behind.
    `POST /ics/remove` returns config the same way `GET /ics` does, so the
    same masking contract applies to it."""
    client.post("/api/connectors/ics", json={"url": SECRET_URL})
    client.post("/api/connectors/ics", json={"url": SECRET_URL_2})
    r = client.post("/api/connectors/ics/remove", json={"id": 0})
    assert r.status_code == 200
    _assert_no_leak(r.json(), SECRET_URL, SECRET_URL_2)
