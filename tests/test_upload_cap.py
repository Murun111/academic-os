"""Upload size cap on document file attachments.

`POST /api/documents/{id}/files` must reject a body over
`DocumentsService.MAX_FILE_BYTES` (25MB) early — off the declared
Content-Length header — before the body is read into memory, not just after
spooling the whole thing and measuring it.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.routers.documents import attach_file, get_service, reset_service, router
from backend.services.documents import DocumentsService


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


# ── black-box: real oversized upload ────────────────────────────


def test_oversized_upload_rejected_not_200(client, monkeypatch):
    """A file whose actual body exceeds the cap is rejected, never stored."""
    monkeypatch.setattr(DocumentsService, "MAX_FILE_BYTES", 1024)
    doc = _add_doc(client)
    r = client.post(
        f"/api/documents/{doc['id']}/files",
        files={"file": ("big.pdf", b"x" * 2048, "application/pdf")},
    )
    assert r.status_code in (400, 413, 422)
    assert r.json()["error"] == "invalid_file"
    # never made it to disk / into the document's file list
    got = client.get(f"/api/documents/{doc['id']}")
    assert got.json()["item"]["files"] == []


def test_upload_under_the_cap_is_accepted(client, monkeypatch):
    # multipart framing (boundary, headers) adds a bit of overhead on top of
    # the file's own bytes, so leave headroom rather than sizing to the cap
    # exactly — this proves under-cap uploads still work, not a boundary value.
    monkeypatch.setattr(DocumentsService, "MAX_FILE_BYTES", 2048)
    doc = _add_doc(client)
    r = client.post(
        f"/api/documents/{doc['id']}/files",
        files={"file": ("ok.pdf", b"x" * 1024, "application/pdf")},
    )
    assert r.status_code == 200
    assert r.json()["item"]["files"][0]["size"] == 1024


# ── unit-level: rejected off Content-Length, body never touched ────


class _FakeHeaders(dict):
    def get(self, key, default=None):  # header lookups are case-sensitive-safe here
        return super().get(key.lower(), default)


class _FakeRequest:
    def __init__(self, content_length: int | None):
        headers = {}
        if content_length is not None:
            headers["content-length"] = str(content_length)
        self.headers = _FakeHeaders(headers)


class _BodyReadForbidden(AssertionError):
    pass


class _FakeUploadFile:
    """Stands in for fastapi.UploadFile; raises if the body is ever read —
    proving the early Content-Length check short-circuits before that."""

    def __init__(self, filename="huge.pdf"):
        self.filename = filename
        self.read_called = False
        self.closed = False

    async def read(self, size: int = -1) -> bytes:
        self.read_called = True
        raise _BodyReadForbidden("body must not be read once Content-Length exceeds the cap")

    async def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_early_rejection_never_reads_the_body(tmp_path, monkeypatch):
    monkeypatch.setenv("ACADEMIC_OS_DATA", str(tmp_path))
    reset_service()
    doc = get_service().add(title="T", kind="other")

    over_cap = DocumentsService.MAX_FILE_BYTES + 1
    req = _FakeRequest(content_length=over_cap)
    upload = _FakeUploadFile()

    result = await attach_file(req, doc.id, upload)

    assert result.status_code in (400, 413, 422)
    assert not upload.read_called
    reset_service()


@pytest.mark.asyncio
async def test_missing_content_length_falls_through_to_chunked_read(tmp_path, monkeypatch):
    """No Content-Length header (e.g. chunked transfer) can't be pre-rejected
    — it must fall through to the bounded-read loop instead of trusting a
    declared size that isn't there."""
    monkeypatch.setenv("ACADEMIC_OS_DATA", str(tmp_path))
    reset_service()
    doc = get_service().add(title="T", kind="other")

    req = _FakeRequest(content_length=None)
    upload = _FakeUploadFile()

    with pytest.raises(_BodyReadForbidden):
        await attach_file(req, doc.id, upload)
    assert upload.read_called
    reset_service()
