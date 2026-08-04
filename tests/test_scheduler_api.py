"""Tests for the scheduler API endpoints (/api/scheduler/*)."""
import pytest
from fastapi.testclient import TestClient

from backend.app import app

SPEC = """---
type: agent
description: scheduled test agent
schedule: "0 8 * * *"
---
Say hello on schedule.
"""


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("ACADEMIC_OS_DATA", str(tmp_path))
    agents_dir = tmp_path / "agents"
    agents_dir.mkdir(parents=True)
    (agents_dir / "cron-agent.md").write_text(SPEC)
    with TestClient(app) as c:
        yield c


def test_scheduler_status_returns_state(client: TestClient):
    r = client.get("/api/scheduler/status")
    assert r.status_code == 200
    body = r.json()
    assert "running" in body
    assert "job_count" in body
    assert "job_names" in body
    # The seeded spec has a cron schedule, so it should be registered.
    assert "cron-agent" in body["job_names"]


def test_scheduler_rescan(client: TestClient):
    r = client.post("/api/scheduler/rescan")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["job_count"] >= 1
