"""Lightweight web search + fetch for agent tools.

Plain httpx — no camofox daemon, no API keys — so it works on any student
machine. Search uses DuckDuckGo's HTML endpoint; fetch strips a page down
to readable text. Both are read-only.
"""
from __future__ import annotations

import html as _html
import re
from urllib.parse import unquote, urlparse, parse_qs

import httpx

_UA = {"User-Agent": "Mozilla/5.0 (Macintosh) AcademicOS/0.1 (+local research agent)"}
_MAX_TEXT = 8000

# DuckDuckGo html results: <a class="result__a" href="...">title</a>
_RESULT_RE = re.compile(
    r'<a[^>]+class="[^"]*result__a[^"]*"[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
    re.S,
)
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"[ \t]+")
_BLOCK_RE = re.compile(r"<(script|style|nav|header|footer|svg|noscript)\b.*?</\1>", re.S | re.I)

# Connectivity failures (DNS/refused/unreachable, or any request timeout) —
# as opposed to a reachable server returning an HTTP error status. Surfaced
# to the model as a plain "offline" signal instead of a raw exception string,
# so it tells the student they're offline rather than hallucinating around
# a stack trace.
_CONNECTION_ERRORS = (httpx.ConnectError, httpx.TimeoutException)
_OFFLINE_RESULT = {"error": "offline", "detail": "no internet connection"}


def _clean(fragment: str) -> str:
    return _html.unescape(_TAG_RE.sub("", fragment)).strip()


def _real_url(href: str) -> str:
    """DDG wraps result links as /l/?uddg=<encoded>. Unwrap them."""
    if href.startswith("//duckduckgo.com/l/") or href.startswith("/l/"):
        q = parse_qs(urlparse(href).query)
        if "uddg" in q:
            return unquote(q["uddg"][0])
    return href


async def search(query: str, limit: int = 8) -> dict:
    """→ {query, results: [{title, url}], count} or an offline error dict."""
    try:
        async with httpx.AsyncClient(timeout=15, headers=_UA, follow_redirects=True) as c:
            r = await c.get("https://html.duckduckgo.com/html/", params={"q": query})
            r.raise_for_status()
    except _CONNECTION_ERRORS:
        return dict(_OFFLINE_RESULT)
    results = []
    for href, title_html in _RESULT_RE.findall(r.text)[:limit]:
        url = _real_url(href)
        title = _clean(title_html)
        if url.startswith("http") and title:
            results.append({"title": title, "url": url})
    return {"query": query, "results": results, "count": len(results)}


async def fetch(url: str) -> dict:
    """→ {url, final_url, text, truncated}. Text-only, scripts/nav stripped.
    Returns an offline error dict on a connectivity failure."""
    try:
        async with httpx.AsyncClient(timeout=20, headers=_UA, follow_redirects=True) as c:
            r = await c.get(url)
            r.raise_for_status()
            body = r.text
            final_url = str(r.url)
    except _CONNECTION_ERRORS:
        return dict(_OFFLINE_RESULT)
    body = _BLOCK_RE.sub(" ", body)
    # keep some block structure as newlines before stripping tags
    body = re.sub(r"</(p|div|li|h[1-6]|tr|br)>", "\n", body, flags=re.I)
    text = _html.unescape(_TAG_RE.sub(" ", body))
    text = "\n".join(_WS_RE.sub(" ", ln).strip() for ln in text.splitlines())
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    truncated = len(text) > _MAX_TEXT
    return {"url": url, "final_url": final_url,
            "text": text[:_MAX_TEXT], "truncated": truncated}
