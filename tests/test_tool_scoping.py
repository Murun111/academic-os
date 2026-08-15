"""Tests for the per-agent tool scoping contract.

Covers both halves of the contract:
- backend/services/tools.py build_tools(allowed=...) — the filter itself.
- backend/services/agent_runner.py AgentRunner._resolve_allowed_tool_names —
  how an agent spec's declared (or undeclared) `tools:` frontmatter maps to
  that filter set.

Default-safe posture (pinned): an agent that declares NO tools gets only
academics.*, calendar.list_events, inbox.list_open, system.audit — never
web.fetch/web.search/vault.write/vault.read/browser.*/code.task/consensus.ask.
"""
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from backend.services.agent_loader import AgentLoader, AgentSpec
from backend.services.agent_runner import AgentRunner, RunStore
from backend.services.tools import build_tools


EXAMPLES_DIR = Path(__file__).resolve().parent.parent / "examples" / "agents"


# === (a)/(b): build_tools(allowed=...) itself ===

def test_build_tools_allowed_filters_to_exact_set():
    tools = build_tools(allowed={"academics.upcoming_deadlines"})
    names = {t.name for t in tools}
    assert names == {"academics.upcoming_deadlines"}


def test_build_tools_none_returns_full_set_incl_web_fetch():
    tools = build_tools()
    names = {t.name for t in tools}
    assert "web.fetch" in names
    assert "web.search" in names
    assert "vault.write" in names
    # Sanity: the full registry is more than just the always-on tools.
    assert len(names) >= 10


# === Fixtures for the runner half ===

@pytest.fixture
def runner(tmp_path: Path) -> AgentRunner:
    ollama = MagicMock()  # not used — no chat() calls in these tests
    loader = AgentLoader(tmp_path / "unused-agents-dir")
    store = RunStore(tmp_path / "runs.jsonl")
    return AgentRunner(ollama=ollama, agent_loader=loader, run_store=store)


# === (c): no declared tools -> default-safe subset ===

def test_no_declared_tools_resolves_to_safe_subset(runner: AgentRunner, tmp_path: Path):
    spec = AgentSpec(
        name="bare",
        prompt="test agent with no tools declared",
        path=tmp_path / "bare.md",
        tools=None,
    )
    allowed = runner._resolve_allowed_tool_names(spec, services={})

    assert "web.fetch" not in allowed
    assert "web.search" not in allowed
    assert "vault.write" not in allowed
    assert "vault.read" not in allowed
    assert "browser.search" not in allowed
    assert "code.task" not in allowed
    assert "consensus.ask" not in allowed

    assert "academics.upcoming_deadlines" in allowed
    assert "academics.student_profile" in allowed
    assert "system.audit" in allowed
    # calendar.list_events / inbox.list_open are exact-safe names but only
    # materialize when their backing service is present; with no services
    # passed here they can't appear even though they're in the safe set.


def test_empty_declared_tools_list_also_resolves_to_safe_subset(runner: AgentRunner, tmp_path: Path):
    """An explicit empty list is falsy, same as None — still safe-subset, not empty."""
    spec = AgentSpec(
        name="bare-empty",
        prompt="test agent with tools: []",
        path=tmp_path / "bare-empty.md",
        tools=[],
    )
    allowed = runner._resolve_allowed_tool_names(spec, services={})
    assert "web.fetch" not in allowed
    assert "academics.upcoming_deadlines" in allowed


# === (d): deadline-watcher example agent excludes the dangerous tools ===

def test_deadline_watcher_example_excludes_web_and_vault(runner: AgentRunner):
    loader = AgentLoader(EXAMPLES_DIR)
    spec = loader.get("deadline-watcher")
    assert spec is not None

    allowed = runner._resolve_allowed_tool_names(spec, services={})

    assert "web.fetch" not in allowed
    assert "web.search" not in allowed
    assert "vault.write" not in allowed
    assert allowed == {"academics.upcoming_deadlines"}


# === (e): scholarship-scout example agent includes web.search ===

def test_scholarship_scout_example_includes_web_search(runner: AgentRunner):
    loader = AgentLoader(EXAMPLES_DIR)
    spec = loader.get("scholarship-scout")
    assert spec is not None

    allowed = runner._resolve_allowed_tool_names(spec, services={})

    assert "web.search" in allowed
    assert "web.fetch" in allowed
    assert "academics.student_profile" in allowed
    assert "academics.add_application" in allowed
    assert "vault.write" not in allowed
