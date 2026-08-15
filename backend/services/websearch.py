"""Lightweight web search + fetch for agent tools.

Plain httpx — no camofox daemon, no API keys — so it works on any student
machine. Search uses DuckDuckGo's HTML endpoint; fetch strips a page down
to readable text. Both are read-only.

Security:
- `fetch()` takes a model/attacker-chosen URL, so it is egress-SSRF-guarded:
  non-http(s) schemes and loopback/private/link-local/reserved destinations
  are refused before the request, and the final URL (after redirects) is
  re-checked so a redirect-to-private-address can't slip the requested-body
  back to the caller.
"""
from __future__ import annotations

import html as _html
import ipaddress
import re
import socket
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


def _blocked_destination(ip_text: str) -> bool:
    """True if `ip_text` (a resolved address) is loopback/private/link-local/
    reserved and therefore not a legitimate egress target."""
    addr = ipaddress.ip_address(ip_text.split("%", 1)[0])  # strip IPv6 zone id
    return (
        addr.is_loopback
        or addr.is_private
        or addr.is_link_local
        or addr.is_reserved
        or addr.is_multicast
        or addr.is_unspecified
    )


def _ssrf_guard(url: str) -> dict | None:
    """Egress SSRF guard for a caller-supplied URL.

    Returns a friendly error dict if `url` must not be fetched (bad scheme,
    unresolvable host, or resolves to a loopback/private/link-local/reserved
    address). Returns None when the URL is safe to fetch. Never raises —
    a DNS failure or malformed URL is treated as "blocked", not an exception.
    """
    try:
        parsed = urlparse(url)
    except ValueError:
        return {"error": "blocked_url", "url": url, "detail": "malformed URL"}
    if parsed.scheme not in ("http", "https"):
        return {"error": "blocked_url", "url": url,
                "detail": f"scheme {parsed.scheme!r} is not allowed"}
    host = parsed.hostname
    if not host:
        return {"error": "blocked_url", "url": url, "detail": "no hostname in URL"}
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return {"error": "blocked_url", "url": url, "detail": "could not resolve host"}
    for info in infos:
        ip_text = info[4][0]
        try:
            if _blocked_destination(ip_text):
                return {"error": "blocked_url", "url": url,
                        "detail": f"{host!r} resolves to a private/internal address"}
        except ValueError:
            return {"error": "blocked_url", "url": url, "detail": "unresolvable address"}
    return None


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
    Returns an offline error dict on a connectivity failure, or a
    `{"error": "blocked_url", ...}` dict if the URL (or its final,
    post-redirect destination) is loopback/private/link-local/reserved."""
    guard_error = _ssrf_guard(url)
    if guard_error is not None:
        return guard_error
    try:
        async with httpx.AsyncClient(timeout=20, headers=_UA, follow_redirects=True) as c:
            r = await c.get(url)
            r.raise_for_status()
            body = r.text
            final_url = str(r.url)
    except _CONNECTION_ERRORS:
        return dict(_OFFLINE_RESULT)
    # Re-check the post-redirect destination: httpx already followed the
    # redirect chain by this point, so this can't stop the request, but it
    # stops a redirect-to-private-address response body from being handed
    # back to the caller.
    if final_url != url:
        final_guard_error = _ssrf_guard(final_url)
        if final_guard_error is not None:
            return final_guard_error
    body = _BLOCK_RE.sub(" ", body)
    # keep some block structure as newlines before stripping tags
    body = re.sub(r"</(p|div|li|h[1-6]|tr|br)>", "\n", body, flags=re.I)
    text = _html.unescape(_TAG_RE.sub(" ", body))
    text = "\n".join(_WS_RE.sub(" ", ln).strip() for ln in text.splitlines())
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    truncated = len(text) > _MAX_TEXT
    return {"url": url, "final_url": final_url,
            "text": text[:_MAX_TEXT], "truncated": truncated}
