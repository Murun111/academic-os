"""Tests for the inbox API endpoints (/api/inbox/*)."""
import pytest
from fastapi.testclient import TestClient

from backend.app import app


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def test_inbox_summary_endpoint(client: TestClient):
    r = client.get("/api/inbox/summary")
    assert r.status_code == 200
    body = r.json()
    assert "total" in body
    assert "open" in body
    assert "done" in body
    assert "by_priority" in body
    assert "overdue" in body
    assert "due_today" in body


def test_inbox_list_endpoint(client: TestClient):
    r = client.get("/api/inbox/items")
    assert r.status_code == 200
    body = r.json()
    assert "items" in body
    assert "count" in body
    assert body["count"] == len(body["items"])


def test_inbox_list_filters_by_status(client: TestClient):
    r = client.get("/api/inbox/items?status=open")
    assert r.status_code == 200


def test_inbox_add_and_retrieve_roundtrip(client: TestClient):
    body = {
        "text": "renew passport by Aug",
        "priority": "high",
        "notes": "downtown SF office",
    }
    r = client.post("/api/inbox/items", json=body)
    assert r.status_code == 200
    assert r.json()["ok"] is True
    item_id = r.json()["item"]["id"]

    r2 = client.get("/api/inbox/items")
    assert r2.status_code == 200
    ids = [i["id"] for i in r2.json()["items"]]
    assert item_id in ids


def test_inbox_add_rejects_empty_text(client: TestClient):
    r = client.post("/api/inbox/items", json={"text": ""})
    # Pydantic min_length=1 → 422
    assert r.status_code == 422


def test_inbox_add_rejects_invalid_priority(client: TestClient):
    r = client.post("/api/inbox/items", json={"text": "x", "priority": "urgent"})
    assert r.status_code == 422


def test_inbox_mark_done_and_reopen(client: TestClient):
    r = client.post("/api/inbox/items", json={"text": "test mark done"})
    item_id = r.json()["item"]["id"]
    # Mark done
    r2 = client.post(f"/api/inbox/items/{item_id}/done")
    assert r2.status_code == 200
    assert r2.json()["item"]["status"] == "done"
    # Reopen
    r3 = client.post(f"/api/inbox/items/{item_id}/reopen")
    assert r3.status_code == 200
    assert r3.json()["item"]["status"] == "open"


def test_inbox_mark_done_unknown_id_returns_404(client: TestClient):
    r = client.post("/api/inbox/items/does-not-exist/done")
    assert r.status_code == 404


def test_inbox_delete(client: TestClient):
    r = client.post("/api/inbox/items", json={"text": "to delete"})
    item_id = r.json()["item"]["id"]
    r2 = client.delete(f"/api/inbox/items/{item_id}")
    assert r2.status_code == 200
    # Confirm gone
    r3 = client.get("/api/inbox/items")
    ids = [i["id"] for i in r3.json()["items"]]
    assert item_id not in ids


def test_inbox_update(client: TestClient):
    r = client.post("/api/inbox/items", json={"text": "orig", "priority": "low"})
    item_id = r.json()["item"]["id"]
    r2 = client.patch(
        f"/api/inbox/items/{item_id}",
        json={"text": "updated", "priority": "high"},
    )
    assert r2.status_code == 200
    assert r2.json()["item"]["text"] == "updated"
    assert r2.json()["item"]["priority"] == "high"
