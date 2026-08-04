"""Tests for backend.app — the FastAPI app and its basic endpoints."""
from fastapi.testclient import TestClient

from backend.app import app


def test_health_returns_ok():
    c = TestClient(app)
    r = c.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_root_serves_frontend_or_redirects():
    """Root should either serve the built frontend or return a useful 404
    with a hint to build the frontend. The exact behavior depends on whether
    the frontend is built; we just check we get *something* sensible."""
    c = TestClient(app)
    r = c.get("/")
    assert r.status_code in (200, 404)
    if r.status_code == 404:
        # Should at least be a JSON error
        body = r.json()
        assert "detail" in body or "message" in body


def test_cors_allows_localhost_dev():
    """Frontend dev server runs on 5173; production on 7878. Both must be allowed."""
    c = TestClient(app)
    r = c.options(
        "/health",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
        },
    )
    # FastAPI CORS preflight returns 200 with the appropriate headers
    assert "access-control-allow-origin" in {k.lower() for k in r.headers.keys()}


def test_websocket_endpoint_exists():
    """The /ws/events endpoint should accept a WebSocket connection."""
    c = TestClient(app)
    with c.websocket_connect("/ws/events") as ws:
        # Server should send a hello message immediately
        msg = ws.receive_json()
        assert msg["type"] in ("hello", "ping", "ready")
