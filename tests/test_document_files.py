"""Tests for document file attachments and default-agent seeding."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.routers.documents import reset_service, router
from backend.services.agent_seed import seed_default_agents
from backend.services.documents import DocumentsService, DocumentsServiceError


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("ACADEMIC_OS_DATA", str(tmp_path))
    reset_service()
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as c:
        yield c
    reset_service()


def _add_doc(client, title="Transcript", kind="transcript"):
    r = client.post("/api/documents", json={"title": title, "kind": kind})
    assert r.status_code == 200
    return r.json()["item"]


def _upload(client, doc_id, name="grades.pdf", data=b"%PDF-1.4 fake"):
    return client.post(
        f"/api/documents/{doc_id}/files",
        files={"file": (name, data, "application/pdf")},
    )


# === attachments ===


def test_upload_download_roundtrip(client):
    doc = _add_doc(client)
    r = _upload(client, doc["id"])
    assert r.status_code == 200
    files = r.json()["item"]["files"]
    assert [f["name"] for f in files] == ["grades.pdf"]
    assert files[0]["size"] == len(b"%PDF-1.4 fake")

    dl = client.get(f"/api/documents/{doc['id']}/files/grades.pdf")
    assert dl.status_code == 200
    assert dl.content == b"%PDF-1.4 fake"


def test_upload_name_collision_gets_suffix(client):
    doc = _add_doc(client)
    _upload(client, doc["id"])
    r = _upload(client, doc["id"])
    names = [f["name"] for f in r.json()["item"]["files"]]
    assert names == ["grades.pdf", "grades-1.pdf"]


def test_remove_file(client):
    doc = _add_doc(client)
    _upload(client, doc["id"])
    r = client.delete(f"/api/documents/{doc['id']}/files/grades.pdf")
    assert r.status_code == 200
    assert r.json()["item"]["files"] == []
    assert client.get(f"/api/documents/{doc['id']}/files/grades.pdf").status_code == 404


def test_delete_document_cascades_files(client, tmp_path):
    doc = _add_doc(client)
    _upload(client, doc["id"])
    files_dir = tmp_path / "data" / "documents" / "files" / doc["id"]
    assert files_dir.is_dir()
    client.delete(f"/api/documents/{doc['id']}")
    assert not files_dir.exists()


def test_path_traversal_rejected(tmp_path):
    svc = DocumentsService(data_dir=tmp_path / "docs")
    doc = svc.add(title="T", kind="other")
    with pytest.raises(DocumentsServiceError):
        svc.attach_file(doc.id, filename="../../evil.sh", data=b"x")
    with pytest.raises(DocumentsServiceError):
        svc.attach_file(doc.id, filename=".hidden", data=b"x")


def test_oversize_rejected(client, monkeypatch):
    monkeypatch.setattr(DocumentsService, "MAX_FILE_BYTES", 10)
    doc = _add_doc(client)
    r = _upload(client, doc["id"], data=b"x" * 11)
    assert r.status_code == 422


# === agent seeding ===


def test_seed_default_agents_into_empty_root(tmp_path, monkeypatch):
    monkeypatch.setenv("ACADEMIC_OS_DATA", str(tmp_path))
    copied = seed_default_agents()
    assert copied >= 2  # deadline-watcher + scholarship-scout
    assert (tmp_path / "agents" / "scholarship-scout.md").is_file()
    # second run: dir is populated → untouched, nothing copied
    assert seed_default_agents() == 0


def test_seed_never_overwrites_user_agents(tmp_path, monkeypatch):
    monkeypatch.setenv("ACADEMIC_OS_DATA", str(tmp_path))
    agents = tmp_path / "agents"
    agents.mkdir(parents=True)
    (agents / "my-agent.md").write_text("# mine")
    assert seed_default_agents() == 0
    assert list(agents.glob("*.md")) == [agents / "my-agent.md"]
