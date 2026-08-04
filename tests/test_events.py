"""Tests for backend.services.events and backend.services.notify.

Events tests are async (pytest-asyncio, @pytest.mark.asyncio per test).
Notify tests are sync with monkeypatch to isolate subprocess and sys.platform.
"""
import asyncio
import subprocess
import sys
from unittest.mock import MagicMock

import pytest

import backend.services.events as events_mod
import backend.services.notify as notify_mod
from backend.services.events import publish, subscribe, subscriber_count, unsubscribe
from backend.services.notify import notify


# ─── Fixture: reset module-level subscriber set before/after each test ─────

@pytest.fixture(autouse=True)
def clean_subscribers():
    events_mod._subscribers.clear()
    yield
    events_mod._subscribers.clear()


# ─── subscribe / unsubscribe / subscriber_count ────────────────────────────

def test_subscribe_returns_bounded_queue():
    q = subscribe()
    assert isinstance(q, asyncio.Queue)
    assert q.maxsize == 200


def test_subscribe_increments_count():
    assert subscriber_count() == 0
    q = subscribe()
    assert subscriber_count() == 1
    unsubscribe(q)
    assert subscriber_count() == 0


def test_subscribe_multiple_queues_counted_separately():
    q1 = subscribe()
    q2 = subscribe()
    assert subscriber_count() == 2
    unsubscribe(q1)
    assert subscriber_count() == 1
    unsubscribe(q2)
    assert subscriber_count() == 0


def test_unsubscribe_unknown_queue_is_noop():
    q = asyncio.Queue()  # never registered
    unsubscribe(q)       # must not raise


# ─── publish: ts stamping ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_publish_stamps_ts_when_missing():
    q = subscribe()
    event = {"type": "test"}
    publish(event)
    received = await asyncio.wait_for(q.get(), timeout=1.0)
    assert "ts" in received
    ts = received["ts"]
    assert "T" in ts and ts.endswith("Z")  # ISO-8601 UTC shape


@pytest.mark.asyncio
async def test_publish_preserves_existing_ts():
    q = subscribe()
    event = {"type": "test", "ts": "2026-01-01T00:00:00Z"}
    publish(event)
    received = await asyncio.wait_for(q.get(), timeout=1.0)
    assert received["ts"] == "2026-01-01T00:00:00Z"


# ─── publish: fan-out ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_publish_delivers_same_dict_to_all_subscribers():
    q1 = subscribe()
    q2 = subscribe()
    event = {"type": "fan", "ts": "2026-01-01T00:00:00Z"}
    publish(event)
    r1 = await asyncio.wait_for(q1.get(), timeout=1.0)
    r2 = await asyncio.wait_for(q2.get(), timeout=1.0)
    assert r1 is r2           # same dict object delivered to every subscriber
    assert r1["type"] == "fan"


# ─── publish: safety guarantees ───────────────────────────────────────────

def test_publish_full_queue_does_not_raise():
    q = subscribe()
    # fill to maxsize so the next put_nowait would raise QueueFull
    for i in range(200):
        q.put_nowait({"i": i})
    assert q.full()
    publish({"type": "overflow", "ts": "2026-01-01T00:00:00Z"})  # must NOT raise


def test_publish_zero_subscribers_does_not_raise():
    assert subscriber_count() == 0
    publish({"type": "lonely", "ts": "2026-01-01T00:00:00Z"})  # must NOT raise


# ─── notify ────────────────────────────────────────────────────────────────

def test_notify_calls_osascript_on_darwin(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setenv("NOTIFY", "1")

    mock_run = MagicMock()
    monkeypatch.setattr(subprocess, "run", mock_run)

    notify("MyTitle", "MyBody")

    mock_run.assert_called_once()
    cmd = mock_run.call_args[0][0]   # first positional arg: the command list
    assert cmd[0] == "osascript"
    assert cmd[1] == "-e"
    script = cmd[2]
    assert "MyTitle" in script
    assert "MyBody" in script


def test_notify_skips_when_notify_env_is_0(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setenv("NOTIFY", "0")

    mock_run = MagicMock()
    monkeypatch.setattr(subprocess, "run", mock_run)

    notify("Hi", "Body")

    mock_run.assert_not_called()


def test_notify_skips_on_non_darwin(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.delenv("NOTIFY", raising=False)

    mock_run = MagicMock()
    monkeypatch.setattr(subprocess, "run", mock_run)

    notify("Hi", "Body")

    mock_run.assert_not_called()


def test_notify_escapes_double_quotes_in_title_and_body(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setenv("NOTIFY", "1")

    mock_run = MagicMock()
    monkeypatch.setattr(subprocess, "run", mock_run)

    notify('He said "hello"', 'Body with "quotes"')

    mock_run.assert_called_once()
    script = mock_run.call_args[0][0][2]
    # Raw " inside title/body must be escaped as \"  in the AppleScript string
    assert '\\"' in script                      # at least one escaped quote present
    assert 'He said \\"hello\\"' in script      # title escaped correctly
    assert 'Body with \\"quotes\\"' in script   # body escaped correctly


def test_notify_escapes_backslashes(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setenv("NOTIFY", "1")

    mock_run = MagicMock()
    monkeypatch.setattr(subprocess, "run", mock_run)

    notify("Path: C:\\Users", "dir\\file")

    mock_run.assert_called_once()
    script = mock_run.call_args[0][0][2]
    # Each \ must be doubled in the AppleScript string
    assert "C:\\\\Users" in script
    assert "dir\\\\file" in script


def test_notify_includes_sound_when_requested(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setenv("NOTIFY", "1")

    mock_run = MagicMock()
    monkeypatch.setattr(subprocess, "run", mock_run)

    notify("Title", "Body", sound=True)

    script = mock_run.call_args[0][0][2]
    assert "Ping" in script


def test_notify_truncates_long_body(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setenv("NOTIFY", "1")

    mock_run = MagicMock()
    monkeypatch.setattr(subprocess, "run", mock_run)

    long_body = "x" * 500
    notify("T", long_body)

    script = mock_run.call_args[0][0][2]
    # The body in the script must not exceed 200 chars (plus escaping overhead)
    # Simplest check: "x" * 201 is NOT in the script
    assert "x" * 201 not in script
    assert "x" * 200 in script  # exactly 200 x's present
