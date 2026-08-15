"""Egress SSRF guard tests for backend.services.websearch.fetch().

Covers every blocked-destination class the guard must refuse before making
any outbound request: loopback, private (RFC1918), link-local, and
non-http(s) schemes. Each blocked case asserts BOTH that fetch() returns the
`{"error": "blocked_url", ...}` dict AND that no outbound GET was ever
attempted (via a fake httpx.AsyncClient that raises if `.get` is called).
A public host is also verified to sail through the guard and reach the
(mocked) HTTP layer.
"""
from __future__ import annotations

import socket

import httpx
import pytest

from backend.services import websearch


# ── DNS mocking helpers ─────────────────────────────────────────────

def _fake_getaddrinfo(dns_map: dict[str, str]):
    """Build a socket.getaddrinfo replacement resolving only hosts in
    `dns_map` (host -> ip). Anything else raises gaierror, same as a real
    unresolvable host — keeps tests from ever touching real DNS/network."""

    def _getaddrinfo(host, *args, **kwargs):
        if host not in dns_map:
            raise socket.gaierror(f"no mock DNS entry for {host!r}")
        ip = dns_map[host]
        family = socket.AF_INET6 if ":" in ip else socket.AF_INET
        sockaddr = (ip, 0, 0, 0) if family == socket.AF_INET6 else (ip, 0)
        return [(family, socket.SOCK_STREAM, 6, "", sockaddr)]

    return _getaddrinfo


# ── fake httpx client that proves no outbound GET happens ──────────

class _AssertNoRequestClient:
    """Stand-in for httpx.AsyncClient that fails the test if `.get` is ever
    invoked. Used to prove the SSRF guard short-circuits fetch() before any
    outbound network call for a blocked destination."""

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def get(self, url, *args, **kwargs):
        raise AssertionError(f"outbound GET must not happen for blocked url: {url}")


def _no_network_client(monkeypatch):
    monkeypatch.setattr(httpx, "AsyncClient", _AssertNoRequestClient)


def _mock_transport_client(monkeypatch, handler):
    """Patch httpx.AsyncClient so fetch()'s real AsyncClient(...) call gets
    an injected MockTransport instead of touching the network."""
    transport = httpx.MockTransport(handler)
    real_async_client = httpx.AsyncClient  # capture before patching to avoid recursion

    def factory(*args, **kwargs):
        kwargs["transport"] = transport
        return real_async_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", factory)


# ── blocked: non-http(s) schemes ────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("url", [
    "file:///etc/passwd",
    "gopher://example.com/1",
])
async def test_non_http_scheme_blocked_no_request(monkeypatch, url):
    _no_network_client(monkeypatch)
    result = await websearch.fetch(url)
    assert result["error"] == "blocked_url"
    assert result["url"] == url


# ── blocked: loopback ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_loopback_literal_ip_blocked_no_request(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo({"127.0.0.1": "127.0.0.1"}))
    _no_network_client(monkeypatch)
    result = await websearch.fetch("http://127.0.0.1:7878/api/secret")
    assert result["error"] == "blocked_url"


@pytest.mark.asyncio
async def test_loopback_localhost_hostname_blocked_no_request(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo({"localhost": "127.0.0.1"}))
    _no_network_client(monkeypatch)
    result = await websearch.fetch("http://localhost:11434/api/generate")
    assert result["error"] == "blocked_url"


# ── blocked: private (RFC1918) ──────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("host,ip", [
    ("10.0.0.5", "10.0.0.5"),
    ("internal.example", "10.1.2.3"),
    ("192.168.1.10", "192.168.1.10"),
    ("router.lan", "192.168.0.1"),
])
async def test_private_address_blocked_no_request(monkeypatch, host, ip):
    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo({host: ip}))
    _no_network_client(monkeypatch)
    result = await websearch.fetch(f"http://{host}/")
    assert result["error"] == "blocked_url"


# ── blocked: link-local ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_link_local_metadata_endpoint_blocked_no_request(monkeypatch):
    monkeypatch.setattr(
        socket, "getaddrinfo",
        _fake_getaddrinfo({"169.254.169.254": "169.254.169.254"}),
    )
    _no_network_client(monkeypatch)
    result = await websearch.fetch("http://169.254.169.254/latest/meta-data/")
    assert result["error"] == "blocked_url"


# ── allowed: public host reaches the (mocked) HTTP layer ────────────

@pytest.mark.asyncio
async def test_public_host_passes_guard(monkeypatch):
    monkeypatch.setattr(
        socket, "getaddrinfo",
        _fake_getaddrinfo({"example.com": "93.184.216.34"}),
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "example.com"
        return httpx.Response(200, text="<html><body><p>hello public web</p></body></html>")

    _mock_transport_client(monkeypatch, handler)

    result = await websearch.fetch("https://example.com/")
    assert "error" not in result
    assert result["url"] == "https://example.com/"
    assert "hello public web" in result["text"]
