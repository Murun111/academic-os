"""Tests for backend.mcp_server — the MCP proxy front door.

Hermetic: no network. We assert the server registers the expected tool surface
and that a tool gracefully reports when the OS is unreachable (httpx mocked to
raise). The real proxy round-trip is covered by manual/live verification.
"""
from __future__ import annotations

import httpx
import pytest

from backend import mcp_server as M


def _fn(tool):
    """FastMCP may return the raw function or a wrapper exposing .fn."""
    return getattr(tool, "fn", tool)


@pytest.mark.asyncio
async def test_server_registers_expected_tools():
    tools = await M.mcp.list_tools()
    names = {t.name for t in tools}
    expected = {
        "consensus_ask", "memory_search", "memory_compact", "agents_list",
        "agent_run", "cos_goal", "calendar_events", "money_summary",
        "inbox_list", "inbox_add", "wiki_search",
        "translate", "translation_add_pair", "translation_capture",
        "translate_auto_cycle", "translate_voice", "translate_murmur_latest",
    }
    assert expected <= names


@pytest.mark.asyncio
async def test_every_tool_has_a_description():
    tools = await M.mcp.list_tools()
    assert all((t.description or "").strip() for t in tools)


@pytest.mark.asyncio
async def test_get_reports_unreachable_os(monkeypatch):
    class _BoomClient:
        def __init__(self, *a, **k): ...
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, *a, **k): raise httpx.ConnectError("refused")
        async def post(self, *a, **k): raise httpx.ConnectError("refused")

    monkeypatch.setattr(M.httpx, "AsyncClient", _BoomClient)
    out = await M._get("/api/money/summary")
    assert "error" in out and "unreachable" in out["error"].lower()
    out2 = await M._post("/api/consensus", {"question": "x"})
    assert "error" in out2 and "unreachable" in out2["error"].lower()
