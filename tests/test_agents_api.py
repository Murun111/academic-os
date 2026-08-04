"""Tests for the agent API endpoints (/api/agents/*)."""
import pytest
from fastapi.testclient import TestClient

from backend.app import app

SPEC = """---
type: agent
description: test demo agent
schedule: "0 8 * * *"
---
Say hello and stop.
"""


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("ACADEMIC_OS_DATA", str(tmp_path))
    agents_dir = tmp_path / "agents"
    agents_dir.mkdir(parents=True)
    (agents_dir / "demo-agent.md").write_text(SPEC)
    with TestClient(app) as c:
        yield c


def test_agents_list_returns_loaded_specs(client: TestClient):
    """Lists the specs found in the data root's agents/ dir."""
    r = client.get("/api/agents")
    assert r.status_code == 200
    body = r.json()
    assert "agents" in body
    assert "count" in body
    assert body["count"] == len(body["agents"])
    names = {a["name"] for a in body["agents"]}
    assert "demo-agent" in names


def test_agents_get_returns_spec(client: TestClient):
    r = client.get("/api/agents/demo-agent")
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "demo-agent"
    assert "prompt" in body


def test_agents_get_404_for_missing(client: TestClient):
    r = client.get("/api/agents/nonexistent-agent-xyz")
    assert r.status_code == 404


def test_agents_runs_list(client: TestClient):
    r = client.get("/api/agents/runs")
    assert r.status_code == 200
    body = r.json()
    assert "runs" in body
    assert "count" in body
    # Newest first
    runs = body["runs"]
    if len(runs) >= 2:
        assert runs[0]["started_at"] >= runs[1]["started_at"]


def test_agents_runs_list_filters_by_agent(client: TestClient):
    r = client.get("/api/agents/runs?agent=demo-agent")
    assert r.status_code == 200
    for run in r.json()["runs"]:
        assert run["agent"] == "demo-agent"
