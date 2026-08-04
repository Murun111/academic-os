"""Tests for the observability endpoints (/api/traces, /api/evals) — roadmap B4."""
import pytest
from fastapi.testclient import TestClient

from backend.app import app


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def test_traces_endpoint_shape(client: TestClient):
    r = client.get("/api/traces?n=5")
    assert r.status_code == 200
    body = r.json()
    assert "count" in body and "records" in body
    assert isinstance(body["records"], list)
    assert body["count"] == len(body["records"])


def test_traces_endpoint_respects_n(client: TestClient):
    r = client.get("/api/traces?n=1")
    assert r.status_code == 200
    assert len(r.json()["records"]) <= 1


def test_evals_endpoint_shape(client: TestClient):
    r = client.get("/api/evals")
    assert r.status_code == 200
    body = r.json()
    assert "latest" in body and "runs" in body
    assert isinstance(body["runs"], list)
    # latest is either None (no runs) or a dict carrying a summary
    assert body["latest"] is None or "summary" in body["latest"]
