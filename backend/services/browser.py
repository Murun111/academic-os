"""Browser service — Python client for camofox-browser.

camofox-browser is an external HTTP server (port 9377 by default) that
wraps a stealth-hardened Firefox and exposes a REST API for AI agents.
This client is the bridge between the agentic-os backend and that
server.

Why: a real research agent needs to fetch modern web pages, not just
HTTP requests. Camoufox handles JS, cookies, and bot-detection so
searches like "@google_search state of CalDAV auth" return real
results, not blocked pages.

Security:
- Refuses non-localhost URLs (SSRF prevention)
- All requests include the API key (Bearer) when configured
- `research_fetch` always closes the tab, even on errors (no tab leaks)
- Read-only by default — there's no helper for arbitrary form submission
"""
from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import httpx
from dotenv import dotenv_values


_ENV_PATH = Path(__file__).parent.parent.parent / "backend" / ".env"
if _ENV_PATH.exists():
    _ENV = dotenv_values(_ENV_PATH)
else:
    _ENV = os.environ


class BrowserServiceError(Exception):
    """Raised when the browser service can't complete a request."""


@dataclass
class Tab:
    id: str
    url: str = ""


@dataclass
class Snapshot:
    url: str
    text: str  # accessibility tree as a single string
    refs_count: int
    truncated: bool
    total_chars: int


@dataclass
class Link:
    url: str
    text: str

    def to_dict(self) -> dict:
        return {"url": self.url, "text": self.text}


class BrowserService:
    """Async Python client for camofox-browser.

    All methods are coroutines. Use `await svc.method()` from another
    coroutine, or `asyncio.run(svc.method())` from sync code.

    Usage:
        svc = BrowserService()  # reads CAMOFOX_URL etc. from env
        health = await svc.health()
        result = await svc.research_fetch("https://example.com")
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        user_id: str = "agentic-os",
        timeout_seconds: float = 30.0,
    ):
        self.base_url = (base_url or _ENV.get("CAMOFOX_URL") or "http://127.0.0.1:9377").rstrip("/")
        self.api_key = api_key or _ENV.get("CAMOFOX_API_KEY") or None
        self.user_id = user_id
        self.timeout = timeout_seconds
        # SSRF guard: only allow localhost. Camofox-browser is meant to
        # be a local process; if you find yourself wanting to point this
        # at a remote host, stop and think about what you're doing.
        from urllib.parse import urlparse
        parsed = urlparse(self.base_url)
        host = (parsed.hostname or "").lower()
        if host not in ("127.0.0.1", "localhost", "::1"):
            raise BrowserServiceError(
                f"BrowserService base_url must be localhost, got {self.base_url!r}. "
                f"Refusing to talk to a remote browser (SSRF prevention)."
            )

    def _headers(self) -> dict:
        h = {"Content-Type": "application/json"}
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        return h

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self.base_url,
            headers=self._headers(),
            timeout=self.timeout,
        )

    async def health(self) -> dict:
        """GET /health. Returns the engine status dict."""
        async with self._client() as c:
            r = await c.get("/health")
        if r.status_code != 200:
            raise BrowserServiceError(f"health check failed: HTTP {r.status_code}: {r.text[:200]}")
        return r.json()

    async def create_tab(self, url: str = "", session_key: str = "default") -> Tab:
        """POST /tabs. Create a new tab, optionally at a URL.

        The sessionKey groups tabs by task — useful for the agent runner
        to keep research runs isolated.
        """
        async with self._client() as c:
            r = await c.post(
                "/tabs",
                json={
                    "userId": self.user_id,
                    "sessionKey": session_key,
                    **({"url": url} if url else {}),
                },
            )
        if r.status_code != 200:
            raise BrowserServiceError(f"create_tab failed: HTTP {r.status_code}: {r.text[:200]}")
        body = r.json()
        return Tab(id=body["tabId"], url=body.get("url", ""))

    async def navigate(
        self,
        tab_id: str,
        url: Optional[str] = None,
        macro: Optional[str] = None,
        query: Optional[str] = None,
    ) -> dict:
        """POST /tabs/:tabId/navigate. Either a URL or a search macro."""
        body: dict = {"userId": self.user_id}
        if macro:
            body["macro"] = macro
            if query:
                body["query"] = query
        elif url:
            body["url"] = url
        else:
            raise BrowserServiceError("navigate requires either url or macro")
        async with self._client() as c:
            r = await c.post(f"/tabs/{tab_id}/navigate", json=body)
        if r.status_code != 200:
            raise BrowserServiceError(f"navigate failed: HTTP {r.status_code}: {r.text[:200]}")
        return r.json()

    async def snapshot(self, tab_id: str) -> Snapshot:
        """GET /tabs/:tabId/snapshot. Returns the accessibility tree as text."""
        async with self._client() as c:
            r = await c.get(f"/tabs/{tab_id}/snapshot", params={"userId": self.user_id})
        if r.status_code != 200:
            raise BrowserServiceError(f"snapshot failed: HTTP {r.status_code}: {r.text[:200]}")
        body = r.json()
        return Snapshot(
            url=body.get("url", ""),
            text=body.get("snapshot", ""),
            refs_count=body.get("refsCount", 0),
            truncated=body.get("truncated", False),
            total_chars=body.get("totalChars", 0),
        )

    async def links(self, tab_id: str, limit: int = 50) -> list[Link]:
        """GET /tabs/:tabId/links. Returns the page's outbound links."""
        async with self._client() as c:
            r = await c.get(
                f"/tabs/{tab_id}/links",
                params={"userId": self.user_id, "limit": limit},
            )
        if r.status_code != 200:
            raise BrowserServiceError(f"links failed: HTTP {r.status_code}: {r.text[:200]}")
        body = r.json()
        return [Link(url=l["url"], text=l.get("text", "")) for l in body.get("links", [])]

    async def close_tab(self, tab_id: str) -> dict:
        """DELETE /tabs/:tabId. Always close tabs when done — no leaks."""
        async with self._client() as c:
            r = await c.delete(f"/tabs/{tab_id}", params={"userId": self.user_id})
        if r.status_code != 200:
            raise BrowserServiceError(f"close_tab failed: HTTP {r.status_code}: {r.text[:200]}")
        return r.json()

    async def research_fetch(
        self,
        url: str,
        session_key: str = "research",
    ) -> dict:
        """High-level helper: open a tab, navigate, snapshot + extract links, close.

        Always closes the tab, even if navigation or snapshot fails.
        This is the main entry point the research agent will use.

        Returns: {
            "url": str,          # the URL you asked for
            "final_url": str,    # where the page actually ended up
            "text": str,         # accessibility tree as text
            "links": [{"url": str, "text": str}],
            "truncated": bool,
            "total_chars": int,
        }
        """
        tab = await self.create_tab(url=url, session_key=session_key)
        try:
            await self.navigate(tab.id, url=url)
            snap = await self.snapshot(tab.id)
            links = await self.links(tab.id)
            return {
                "url": url,
                "final_url": snap.url,
                "text": snap.text,
                "links": [l.to_dict() for l in links],
                "truncated": snap.truncated,
                "total_chars": snap.total_chars,
            }
        finally:
            await self.close_tab(tab.id)

    async def research_search(
        self,
        query: str,
        macro: str = "@google_search",
        session_key: str = "research",
    ) -> dict:
        """High-level helper: run a search via macro, return SERP content + links."""
        tab = await self.create_tab(session_key=session_key)
        try:
            await self.navigate(tab.id, macro=macro, query=query)
            # Search result pages benefit from a small wait so JS-rendered
            # content lands before we snapshot. camofox doesn't return
            # refsAvailable=True for SERPs (it returns googleSerp=true),
            # so the snapshot is from a different code path that may
            # need a beat to settle.
            await asyncio.sleep(1.5)
            snap = await self.snapshot(tab.id)
            links = await self.links(tab.id)
            return {
                "query": query,
                "macro": macro,
                "final_url": snap.url,
                "text": snap.text,
                "links": [l.to_dict() for l in links],
                "truncated": snap.truncated,
                "total_chars": snap.total_chars,
            }
        finally:
            await self.close_tab(tab.id)
