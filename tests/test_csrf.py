"""Tests for the CSRF origin-check middleware in backend.app.

The middleware (backend.app.csrf_origin_check) rejects mutating
(POST/PUT/PATCH/DELETE) requests to /api/* paths when the request carries an
Origin header that isn't in the allowed set. Requests with no Origin header
(curl, native clients, this test suite by default) are allowed through, and
GET/HEAD/OPTIONS are always allowed regardless of Origin.
"""
from fastapi.testclient import TestClient

from backend.app import app

_EVIL_ORIGIN = "https://evil.example"
_ALLOWED_ORIGIN = "http://localhost:7878"


def _is_forbidden_origin(r) -> bool:
    return r.status_code == 403 and r.json().get("error") == "forbidden_origin"


def test_evil_origin_blocks_restore():
    c = TestClient(app)
    r = c.post("/api/system/restore", headers={"Origin": _EVIL_ORIGIN})
    assert r.status_code == 403
    assert r.json() == {"error": "forbidden_origin"}


def test_allowed_origin_reaches_restore_handler():
    """Origin in the allowed set must NOT be blocked — the request should
    reach the actual handler (whatever it returns)."""
    c = TestClient(app)
    r = c.post("/api/system/restore", headers={"Origin": _ALLOWED_ORIGIN})
    assert not _is_forbidden_origin(r)


def test_no_origin_header_allowed():
    """No Origin header at all (curl, native clients, our own test suite)
    must NOT be blocked."""
    c = TestClient(app)
    r = c.post("/api/system/restore")
    assert not _is_forbidden_origin(r)


def test_get_with_evil_origin_allowed():
    """GET is never subject to the CSRF check, even with a hostile Origin."""
    c = TestClient(app)
    r = c.get("/api/system/backup", headers={"Origin": _EVIL_ORIGIN})
    assert not _is_forbidden_origin(r)
    assert r.status_code != 403


# --- Spot-checks across the wider mutating-endpoint matrix ---------------


def test_evil_origin_blocks_inbox_add_item():
    c = TestClient(app)
    r = c.post(
        "/api/inbox/items",
        json={"text": "csrf probe"},
        headers={"Origin": _EVIL_ORIGIN},
    )
    assert r.status_code == 403
    assert r.json() == {"error": "forbidden_origin"}


def test_allowed_origin_reaches_inbox_add_item_handler():
    """Uses the lifespan-managed client (`with`) so app.state.inbox exists —
    the CSRF check itself doesn't need this, but the real handler does."""
    with TestClient(app) as c:
        r = c.post(
            "/api/inbox/items",
            json={"text": "csrf probe"},
            headers={"Origin": _ALLOWED_ORIGIN},
        )
    assert not _is_forbidden_origin(r)
    assert r.status_code == 200


def test_evil_origin_blocks_memory_forget_all():
    c = TestClient(app)
    r = c.post("/api/memory/forget_all", headers={"Origin": _EVIL_ORIGIN})
    assert r.status_code == 403
    assert r.json() == {"error": "forbidden_origin"}


def test_evil_origin_blocks_memory_item_delete():
    c = TestClient(app)
    r = c.delete(
        "/api/memory/items/does-not-exist",
        headers={"Origin": _EVIL_ORIGIN},
    )
    assert r.status_code == 403
    assert r.json() == {"error": "forbidden_origin"}


def test_no_origin_header_reaches_memory_item_delete_handler():
    c = TestClient(app)
    r = c.delete("/api/memory/items/does-not-exist")
    assert not _is_forbidden_origin(r)
    # No such item — reaches the real handler and 404s there, not at CSRF.
    assert r.status_code == 404
