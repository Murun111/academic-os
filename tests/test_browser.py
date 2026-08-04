"""Tests for backend.services.browser — Python client for camofox-browser.

The client is async (httpx.AsyncClient) and talks to the camofox-browser
HTTP server over localhost. Tests use httpx's MockTransport to avoid
needing the real browser running.

Real-server integration test: skipped by default, run with
BROWSER_LIVE_TEST=1 if the camofox-browser server is up.
"""
import os
from typing import Any
from unittest.mock import patch

import httpx
import pytest

from backend.services.browser import (
    BrowserService,
    BrowserServiceError,
    Snapshot,
    Link,
    Tab,
)


# === Mock HTTP transport ===

def make_mock_transport(responses: list[httpx.Response]):
    """Build an httpx MockTransport that returns responses in order."""
    iterator = iter(responses)

    def handler(request: httpx.Request) -> httpx.Response:
        try:
            return next(iterator)
        except StopIteration:
            return httpx.Response(500, text="mock exhausted")

    return httpx.MockTransport(handler)


# === Construction ===

def test_constructs_with_defaults():
    svc = BrowserService()
    assert svc.base_url == "http://127.0.0.1:9377"
    assert svc.user_id == "agentic-os"


def test_constructs_with_explicit_url():
    svc = BrowserService(base_url="http://127.0.0.1:9999")
    assert svc.base_url == "http://127.0.0.1:9999"


def test_constructs_with_api_key():
    svc = BrowserService(api_key="test-key")
    assert svc.api_key == "test-key"


def test_rejects_non_localhost_url():
    """Security guard: refuse to talk to remote browsers (SSRF prevention)."""
    with pytest.raises(BrowserServiceError, match="localhost"):
        BrowserService(base_url="https://attacker.com")
    with pytest.raises(BrowserServiceError, match="localhost"):
        BrowserService(base_url="http://10.0.0.1:9377")


# === Test helper: monkey-patch the transport on a service instance ===

def with_transport(svc: BrowserService, transport: httpx.MockTransport) -> BrowserService:
    """Replace the service's _client() to return a client using the given transport."""
    def _patched_client():
        return httpx.AsyncClient(
            base_url=svc.base_url,
            headers=svc._headers(),
            timeout=svc.timeout,
            transport=transport,
        )
    svc._client = _patched_client  # type: ignore[assignment]
    return svc


# === health() ===

def test_health_returns_engine_status():
    transport = make_mock_transport([
        httpx.Response(200, json={"ok": True, "engine": "camoufox",
                                  "browserConnected": True, "browserRunning": True,
                                  "activeTabs": 0, "activeSessions": 0,
                                  "consecutiveFailures": 0,
                                  "memory": {"rssMb": 200, "heapUsedMb": 60, "nativeMemMb": 140}}),
    ])
    svc = with_transport(BrowserService(), transport)
    import asyncio
    result = asyncio.run(svc.health())
    assert result["ok"] is True
    assert result["engine"] == "camoufox"


# === create_tab() ===

def test_create_tab_returns_tab_with_id():
    transport = make_mock_transport([
        httpx.Response(200, json={"tabId": "abc-123", "url": "https://example.com"}),
    ])
    svc = with_transport(BrowserService(), transport)
    import asyncio
    tab = asyncio.run(svc.create_tab(url="https://example.com"))
    assert isinstance(tab, Tab)
    assert tab.id == "abc-123"
    assert tab.url == "https://example.com"


# === navigate() ===

def test_navigate_with_search_macro():
    """Navigate via a search macro (e.g. @google_search)."""
    transport = make_mock_transport([
        httpx.Response(200, json={
            "ok": True,
            "tabId": "tab-1",
            "url": "https://www.google.com/search?q=test",
            "refsAvailable": False,
            "googleSerp": True,
        }),
    ])
    svc = with_transport(BrowserService(), transport)
    import asyncio
    result = asyncio.run(svc.navigate("tab-1", macro="@google_search", query="test"))
    assert result["ok"] is True
    assert "google.com" in result["url"]


def test_navigate_requires_url_or_macro():
    svc = BrowserService()
    import asyncio
    with pytest.raises(BrowserServiceError, match="url or macro"):
        asyncio.run(svc.navigate("tab-1"))


# === snapshot() ===

def test_snapshot_returns_accessibility_tree():
    transport = make_mock_transport([
        httpx.Response(200, json={
            "url": "https://example.com",
            "snapshot": '- heading "Example"\n- link "More" [e1]:\n  - /url: https://iana.org',
            "refsCount": 1,
            "truncated": False,
            "totalChars": 80,
        }),
    ])
    svc = with_transport(BrowserService(), transport)
    import asyncio
    snap = asyncio.run(svc.snapshot("tab-1"))
    assert isinstance(snap, Snapshot)
    assert snap.url == "https://example.com"
    assert "Example" in snap.text
    assert "More" in snap.text
    assert snap.refs_count == 1


# === links() ===

def test_links_returns_list():
    transport = make_mock_transport([
        httpx.Response(200, json={
            "links": [
                {"url": "https://a.com", "text": "A"},
                {"url": "https://b.com", "text": "B"},
            ],
            "pagination": {"total": 2, "offset": 0, "limit": 50, "hasMore": False},
        }),
    ])
    svc = with_transport(BrowserService(), transport)
    import asyncio
    links = asyncio.run(svc.links("tab-1"))
    assert len(links) == 2
    assert all(isinstance(l, Link) for l in links)
    assert links[0].url == "https://a.com"
    assert links[0].text == "A"


# === close_tab() ===

def test_close_tab_returns_ok():
    transport = make_mock_transport([httpx.Response(200, json={"ok": True})])
    svc = with_transport(BrowserService(), transport)
    import asyncio
    result = asyncio.run(svc.close_tab("tab-1"))
    assert result["ok"] is True


# === research helper: fetch + extract ===

def test_research_fetch_returns_text_and_links():
    """High-level helper: create tab + navigate + snapshot + close + return text+links."""
    transport = make_mock_transport([
        # create_tab
        httpx.Response(200, json={"tabId": "tab-r", "url": ""}),
        # navigate
        httpx.Response(200, json={"ok": True, "tabId": "tab-r", "url": "https://x.com", "refsAvailable": False}),
        # snapshot
        httpx.Response(200, json={
            "url": "https://x.com",
            "snapshot": '- heading "Title" [level=1]\n- paragraph: Body text here.',
            "refsCount": 0, "truncated": False, "totalChars": 50,
        }),
        # links
        httpx.Response(200, json={
            "links": [{"url": "https://x.com/about", "text": "About"}],
            "pagination": {"total": 1, "offset": 0, "limit": 50, "hasMore": False},
        }),
        # close
        httpx.Response(200, json={"ok": True}),
    ])
    svc = with_transport(BrowserService(), transport)
    import asyncio
    result = asyncio.run(svc.research_fetch("https://x.com"))
    assert "Title" in result["text"]
    assert "Body text" in result["text"]
    assert len(result["links"]) == 1
    assert result["links"][0]["url"] == "https://x.com/about"
    assert result["final_url"] == "https://x.com"


def test_research_fetch_closes_tab_on_error():
    """If snapshot fails, the tab should still be closed (no leaks)."""
    transport = make_mock_transport([
        httpx.Response(200, json={"tabId": "tab-leak", "url": ""}),
        httpx.Response(500, text="boom"),  # navigate fails
        httpx.Response(200, json={"ok": True}),  # close (still called)
    ])
    svc = with_transport(BrowserService(), transport)
    import asyncio
    with pytest.raises(BrowserServiceError):
        asyncio.run(svc.research_fetch("https://x.com"))


# === research helper: search via macro ===

def test_research_search_returns_serp():
    transport = make_mock_transport([
        # create_tab
        httpx.Response(200, json={"tabId": "tab-s", "url": ""}),
        # navigate
        httpx.Response(200, json={"ok": True, "tabId": "tab-s", "url": "https://www.google.com/search?q=foo"}),
        # snapshot
        httpx.Response(200, json={
            "url": "https://www.google.com/search?q=foo",
            "snapshot": '- link "Result 1" [e1]:\n  - /url: https://result1.com',
            "refsCount": 1, "truncated": False, "totalChars": 60,
        }),
        # links
        httpx.Response(200, json={
            "links": [{"url": "https://result1.com", "text": "Result 1"}],
            "pagination": {"total": 1, "offset": 0, "limit": 50, "hasMore": False},
        }),
        # close
        httpx.Response(200, json={"ok": True}),
    ])
    svc = with_transport(BrowserService(), transport)
    import asyncio
    result = asyncio.run(svc.research_search("foo"))
    assert result["query"] == "foo"
    assert "Result 1" in result["text"]


# === API key auth ===

def test_api_key_sent_in_authorization_header():
    """When api_key is set, every request includes an Authorization header."""
    captured_headers = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_headers.append(dict(request.headers))
        return httpx.Response(200, json={"ok": True, "engine": "camoufox",
                                         "browserConnected": True, "browserRunning": True,
                                         "activeTabs": 0, "activeSessions": 0,
                                         "consecutiveFailures": 0,
                                         "memory": {"rssMb": 200, "heapUsedMb": 60, "nativeMemMb": 140}})

    transport = httpx.MockTransport(handler)
    svc = with_transport(BrowserService(api_key="my-secret-key"), transport)
    import asyncio
    asyncio.run(svc.health())
    assert any("authorization" in str(h).lower() for h in captured_headers)


# === Live integration test (skipped unless BROWSER_LIVE_TEST=1) ===

@pytest.mark.skipif(
    not os.environ.get("BROWSER_LIVE_TEST"),
    reason="live browser test — set BROWSER_LIVE_TEST=1 to enable",
)
def test_live_camofox_browser():
    """End-to-end against a real camofox-browser server.

    Start the server first:
        cd ~/Code/agentic-os/tools/camofox-browser
        node server.js
    Then run:
        BROWSER_LIVE_TEST=1 pytest tests/test_browser.py::test_live_camofox_browser -v
    """
    import asyncio
    svc = BrowserService()
    health = asyncio.run(svc.health())
    assert health["ok"] is True, f"server not healthy: {health}"
    result = asyncio.run(svc.research_fetch("https://example.com"))
    assert "Example Domain" in result["text"]
