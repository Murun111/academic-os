"""Tests for the Documents Hub API endpoints (/api/documents/*)."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.routers.documents import router, reset_service


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("ACADEMIC_OS_DATA", str(tmp_path))
    reset_service()
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as c:
        yield c
    reset_service()


def _add(client, title="My Essay", kind="essay", **extra):
    body = {"title": title, "kind": kind, **extra}
    r = client.post("/api/documents", json=body)
    assert r.status_code == 200, r.text
    return r.json()["item"]


def test_add_and_list(client: TestClient):
    item = _add(client)
    assert item["kind"] == "essay"
    assert item["status"] == "draft"
    assert item["version"] == 1
    assert item["history"] == []

    r = client.get("/api/documents")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 1
    assert body["items"][0]["id"] == item["id"]


def test_get_document(client: TestClient):
    item = _add(client)
    r = client.get(f"/api/documents/{item['id']}")
    assert r.status_code == 200
    assert r.json()["item"]["id"] == item["id"]


def test_get_unknown_id_returns_404(client: TestClient):
    r = client.get("/api/documents/does-not-exist")
    assert r.status_code == 404


def test_update_does_not_bump_version(client: TestClient):
    item = _add(client)
    r = client.patch(f"/api/documents/{item['id']}", json={"status": "in_review"})
    assert r.status_code == 200
    updated = r.json()["item"]
    assert updated["status"] == "in_review"
    assert updated["version"] == 1
    assert updated["history"] == []


def test_bump_version_increments_and_appends_history(client: TestClient):
    item = _add(client)
    r = client.post(f"/api/documents/{item['id']}/versions", json={"note": "second draft"})
    assert r.status_code == 200
    bumped = r.json()["item"]
    assert bumped["version"] == 2
    assert len(bumped["history"]) == 1
    assert bumped["history"][0]["version"] == 2
    assert bumped["history"][0]["note"] == "second draft"

    r2 = client.post(f"/api/documents/{item['id']}/versions", json={"note": "third draft"})
    bumped2 = r2.json()["item"]
    assert bumped2["version"] == 3
    assert len(bumped2["history"]) == 2


def test_bump_version_unknown_id_returns_404(client: TestClient):
    r = client.post("/api/documents/does-not-exist/versions", json={"note": "x"})
    assert r.status_code == 404


def test_link_is_idempotent(client: TestClient):
    item = _add(client)
    r1 = client.post(f"/api/documents/{item['id']}/link", json={"application_id": "app-1"})
    assert r1.status_code == 200
    assert r1.json()["item"]["linked_application_ids"] == ["app-1"]

    r2 = client.post(f"/api/documents/{item['id']}/link", json={"application_id": "app-1"})
    assert r2.status_code == 200
    assert r2.json()["item"]["linked_application_ids"] == ["app-1"]


def test_unlink_removes_link(client: TestClient):
    item = _add(client)
    client.post(f"/api/documents/{item['id']}/link", json={"application_id": "app-1"})
    r = client.post(f"/api/documents/{item['id']}/unlink", json={"application_id": "app-1"})
    assert r.status_code == 200
    assert r.json()["item"]["linked_application_ids"] == []

    # unlinking again is a no-op, not an error
    r2 = client.post(f"/api/documents/{item['id']}/unlink", json={"application_id": "app-1"})
    assert r2.status_code == 200
    assert r2.json()["item"]["linked_application_ids"] == []


def test_filter_by_kind(client: TestClient):
    _add(client, title="Essay 1", kind="essay")
    _add(client, title="CV 1", kind="cv")
    r = client.get("/api/documents?kind=cv")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 1
    assert body["items"][0]["kind"] == "cv"


def test_filter_by_application_id(client: TestClient):
    doc_a = _add(client, title="Essay A")
    doc_b = _add(client, title="Essay B")
    client.post(f"/api/documents/{doc_a['id']}/link", json={"application_id": "app-42"})

    r = client.get("/api/documents?application_id=app-42")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 1
    assert body["items"][0]["id"] == doc_a["id"]

    r2 = client.get("/api/documents?application_id=app-does-not-exist")
    assert r2.json()["count"] == 0
    assert doc_b["id"] not in [i["id"] for i in r2.json()["items"]]


def test_delete_document(client: TestClient):
    item = _add(client)
    r = client.delete(f"/api/documents/{item['id']}")
    assert r.status_code == 200
    r2 = client.get(f"/api/documents/{item['id']}")
    assert r2.status_code == 404


def test_delete_unknown_id_returns_404(client: TestClient):
    r = client.delete("/api/documents/does-not-exist")
    assert r.status_code == 404


def test_add_rejects_invalid_kind(client: TestClient):
    r = client.post("/api/documents", json={"title": "x", "kind": "not-a-kind"})
    assert r.status_code == 422


def test_add_rejects_empty_title(client: TestClient):
    r = client.post("/api/documents", json={"title": "", "kind": "essay"})
    assert r.status_code == 422


def test_update_rejects_invalid_status(client: TestClient):
    item = _add(client)
    r = client.patch(f"/api/documents/{item['id']}", json={"status": "not-a-status"})
    assert r.status_code == 422
