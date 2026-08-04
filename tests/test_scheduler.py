"""Tests for backend.services.scheduler — cron + vault-event triggers.

Tests the AgentScheduler (cron) and TriggerEngine (vault events)
in isolation, with a mock AgentRunner.
"""
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.services.agent_loader import AgentLoader
from backend.services.agent_runner import AgentRunner, RunStatus
from backend.services.scheduler import (
    AgentScheduler,
    TriggerEngine,
    TriggerDedupe,
)


# === Fixtures ===

@pytest.fixture
def spec_dir(tmp_path: Path) -> Path:
    agents = tmp_path / "agents"
    agents.mkdir()
    return agents


def write_spec(agents: Path, name: str, **fields) -> Path:
    """Write a spec with given frontmatter fields. Always sets type: agent."""
    fm_lines = ["type: agent", f"name: {name}"]
    for k, v in fields.items():
        if isinstance(v, bool):
            fm_lines.append(f"{k}: {'true' if v else 'false'}")
        elif v is None:
            continue
        else:
            fm_lines.append(f"{k}: {v}")
    frontmatter = "\n".join(fm_lines)
    body = f"body for {name}"
    content = f"---\n{frontmatter}\n---\n{body}\n"
    p = agents / f"{name}.md"
    p.write_text(content)
    return p


@pytest.fixture
def mock_runner() -> AgentRunner:
    runner = MagicMock(spec=AgentRunner)
    runner.run = AsyncMock(return_value=MagicMock(id="fake-id", status=RunStatus.SUCCESS))
    return runner


# === TriggerDedupe ===

def test_dedupe_allows_first_event():
    d = TriggerDedupe(cooldown_seconds=60)
    assert d.should_fire("agent-a", "/path", "modified") is True


def test_dedupe_blocks_recent_same_event():
    d = TriggerDedupe(cooldown_seconds=60)
    d.should_fire("agent-a", "/path", "modified")
    # Immediate second call → blocked
    assert d.should_fire("agent-a", "/path", "modified") is False


def test_dedupe_allows_different_path():
    d = TriggerDedupe(cooldown_seconds=60)
    d.should_fire("agent-a", "/path1", "modified")
    assert d.should_fire("agent-a", "/path2", "modified") is True


def test_dedupe_allows_different_agent():
    d = TriggerDedupe(cooldown_seconds=60)
    d.should_fire("agent-a", "/path", "modified")
    assert d.should_fire("agent-b", "/path", "modified") is True


def test_dedupe_allows_different_kind():
    d = TriggerDedupe(cooldown_seconds=60)
    d.should_fire("agent-a", "/path", "modified")
    assert d.should_fire("agent-a", "/path", "created") is True


def test_dedupe_respects_cooldown():
    d = TriggerDedupe(cooldown_seconds=0)  # zero cooldown
    d.should_fire("agent-a", "/path", "modified")
    import time
    time.sleep(0.01)
    assert d.should_fire("agent-a", "/path", "modified") is True


# === AgentScheduler (cron) ===

def test_scheduler_starts_empty(spec_dir, mock_runner):
    loader = AgentLoader(spec_dir)
    sched = AgentScheduler(loader, mock_runner)
    # No specs → no jobs
    assert sched.job_count() == 0


def test_scheduler_registers_cron_job(spec_dir, mock_runner):
    write_spec(spec_dir, "daily", schedule="0 7 * * *")
    loader = AgentLoader(spec_dir)
    sched = AgentScheduler(loader, mock_runner)
    sched.start()
    try:
        assert sched.job_count() == 1
        assert "daily" in sched.job_names()
    finally:
        sched.stop()


def test_scheduler_skips_agents_without_schedule(spec_dir, mock_runner):
    write_spec(spec_dir, "trigger-only")  # no schedule
    loader = AgentLoader(spec_dir)
    sched = AgentScheduler(loader, mock_runner)
    sched.start()
    try:
        assert sched.job_count() == 0
    finally:
        sched.stop()


def test_scheduler_skips_disabled_agents(spec_dir, mock_runner):
    write_spec(spec_dir, "off", schedule="0 7 * * *", enabled=False)
    loader = AgentLoader(spec_dir)
    sched = AgentScheduler(loader, mock_runner)
    sched.start()
    try:
        assert sched.job_count() == 0
    finally:
        sched.stop()


def test_scheduler_rescans_on_demand(spec_dir, mock_runner):
    loader = AgentLoader(spec_dir)
    sched = AgentScheduler(loader, mock_runner)
    sched.start()
    try:
        assert sched.job_count() == 0
        # Add a spec dynamically
        write_spec(spec_dir, "late-add", schedule="0 8 * * *")
        sched.rescan()
        assert sched.job_count() == 1
        assert "late-add" in sched.job_names()
    finally:
        sched.stop()


# === TriggerEngine (vault events) ===

def test_trigger_engine_matches_path(spec_dir, mock_runner):
    write_spec(spec_dir, "triage", trigger="on_vault_event", trigger_path="Agentic OS/data/inbox/")
    loader = AgentLoader(spec_dir)
    engine = TriggerEngine(loader, mock_runner, dedupe=TriggerDedupe(cooldown_seconds=0))

    event = {"path": "Agentic OS/data/inbox/items.jsonl", "kind": "modified"}
    matched = engine.match(event)
    assert "triage" in matched


def test_trigger_engine_no_match_when_path_differs(spec_dir, mock_runner):
    write_spec(spec_dir, "triage", trigger="on_vault_event", trigger_path="Agentic OS/data/inbox/")
    loader = AgentLoader(spec_dir)
    engine = TriggerEngine(loader, mock_runner, dedupe=TriggerDedupe(cooldown_seconds=0))

    event = {"path": "Agentic OS/notes/daily.md", "kind": "modified"}
    matched = engine.match(event)
    assert matched == []


def test_trigger_engine_dedupes_rapid_events(spec_dir, mock_runner):
    write_spec(spec_dir, "triage", trigger="on_vault_event", trigger_path="Agentic OS/data/inbox/")
    loader = AgentLoader(spec_dir)
    engine = TriggerEngine(loader, mock_runner, dedupe=TriggerDedupe(cooldown_seconds=60))

    event = {"path": "Agentic OS/data/inbox/items.jsonl", "kind": "modified"}
    matched1 = engine.match(event)
    matched2 = engine.match(event)  # should be deduped
    assert "triage" in matched1
    assert matched2 == []


@pytest.mark.asyncio
async def test_trigger_engine_fires_runner(spec_dir, mock_runner):
    write_spec(spec_dir, "triage", trigger="on_vault_event", trigger_path="Agentic OS/data/inbox/")
    loader = AgentLoader(spec_dir)
    engine = TriggerEngine(loader, mock_runner, dedupe=TriggerDedupe(cooldown_seconds=0))

    event = {"path": "Agentic OS/data/inbox/items.jsonl", "kind": "modified"}
    fired = await engine.fire(event)
    assert "triage" in fired
    mock_runner.run.assert_awaited_once()
    # Verify the call args
    call = mock_runner.run.await_args
    assert call.kwargs["agent_name"] == "triage"
    assert call.kwargs["trigger"] == "vault_event:Agentic OS/data/inbox/items.jsonl:modified"
    assert call.kwargs["trigger_context"] == event


def test_trigger_engine_no_match_for_manual_only_agent(spec_dir, mock_runner):
    write_spec(spec_dir, "manual", trigger=None, trigger_path=None)
    loader = AgentLoader(spec_dir)
    engine = TriggerEngine(loader, mock_runner, dedupe=TriggerDedupe(cooldown_seconds=0))

    event = {"path": "anything", "kind": "modified"}
    matched = engine.match(event)
    assert matched == []


def test_trigger_engine_skips_disabled(spec_dir, mock_runner):
    write_spec(spec_dir, "off", trigger="on_vault_event", trigger_path="Agentic OS/", enabled=False)
    loader = AgentLoader(spec_dir)
    engine = TriggerEngine(loader, mock_runner, dedupe=TriggerDedupe(cooldown_seconds=0))

    event = {"path": "Agentic OS/x.md", "kind": "modified"}
    matched = engine.match(event)
    assert matched == []


# === Path matching edge cases ===

def test_trigger_path_prefix_match(spec_dir, mock_runner):
    """The trigger_path is a prefix; any file under it matches."""
    write_spec(spec_dir, "p", trigger="on_vault_event", trigger_path="Agentic OS/data/inbox/")
    loader = AgentLoader(spec_dir)
    engine = TriggerEngine(loader, mock_runner, dedupe=TriggerDedupe(cooldown_seconds=0))

    # Exact match
    assert "p" in engine.match({"path": "Agentic OS/data/inbox/items.jsonl", "kind": "modified"})
    # Nested file (not really possible with JSONL, but defensive)
    # The path is treated as a prefix — if the trigger_path ends with '/',
    # any sub-path matches; otherwise it's an equality check.
    assert "p" in engine.match({"path": "Agentic OS/data/inbox/sub/file.md", "kind": "modified"})
    # Sibling — should NOT match
    assert engine.match({"path": "Agentic OS/data/money/x.jsonl", "kind": "modified"}) == []


def test_trigger_path_exact_match_when_no_trailing_slash(spec_dir, mock_runner):
    write_spec(spec_dir, "p", trigger="on_vault_event", trigger_path="CLAUDE.md")
    loader = AgentLoader(spec_dir)
    engine = TriggerEngine(loader, mock_runner, dedupe=TriggerDedupe(cooldown_seconds=0))

    assert "p" in engine.match({"path": "CLAUDE.md", "kind": "modified"})
    assert engine.match({"path": "CLAUDE.md.bak", "kind": "modified"}) == []
