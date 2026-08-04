"""Tests for backend.services.agent_memory — Module B (Phase 2).

All tests run OFFLINE:
- backend.vault.resolve_vault_path → tmp_path  (no iCloud touched)
- backend.services.memory.consolidate_thread  → async stub  (no Ollama)

Coverage:
- COO / daily-brief agents file to output/daily/<date>.md.
- Other agents file to output/<name>/<date>.md.
- Fresh note includes YAML frontmatter with last_updated: today.
- Fresh note includes the run section header + result body.
- record_run returns {"filed": True, "note": ..., "memory": ...}.
- Not-success or empty result returns {"filed": False, "reason": ...}.
- consolidate_thread raising does NOT prevent filing (memory={}).
- Second run on the same day appends; last_updated appears exactly once.
- RunStatus enum value treated correctly.
"""
from __future__ import annotations

import time
from pathlib import Path
from types import SimpleNamespace

import pytest

import backend.services.agent_memory as agent_memory


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_run(
    agent: str = "coo",
    status: str = "success",
    result: str = "Daily brief produced.",
    trigger: str = "cron",
    run_id: str = "abc123",
) -> SimpleNamespace:
    return SimpleNamespace(
        id=run_id,
        agent=agent,
        status=status,
        result=result,
        trigger=trigger,
        started_at="2026-06-26T07:00:00",
    )


def make_spec(name: str = "coo", description: str = "COO daily brief agent") -> SimpleNamespace:
    return SimpleNamespace(name=name, description=description)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def patch_vault(monkeypatch, tmp_path: Path):
    """Redirect all vault I/O to tmp_path — mirrors test_memory_writer.py style."""
    monkeypatch.setattr("backend.vault.resolve_vault_path", lambda: tmp_path)
    return tmp_path


@pytest.fixture(autouse=True)
def patch_memory(monkeypatch):
    """Stub out memory.consolidate_thread to avoid Ollama calls."""
    from backend.services.memory_types import ConsolidationResult

    async def _stub(thread: dict) -> ConsolidationResult:
        return ConsolidationResult(thread_id=thread.get("id", ""), error="")

    monkeypatch.setattr("backend.services.memory.consolidate_thread", _stub)


# ── Success path: COO → daily note ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_coo_files_to_daily_note(tmp_path: Path):
    today = time.strftime("%Y-%m-%d", time.gmtime())
    out = await agent_memory.record_run(make_run(agent="coo"), make_spec())

    assert out["filed"] is True
    expected = f"output/daily/{today}.md"
    assert out["note"] == expected
    assert (tmp_path / expected).exists()


@pytest.mark.asyncio
async def test_coo_note_has_frontmatter_with_today(tmp_path: Path):
    today = time.strftime("%Y-%m-%d", time.gmtime())
    await agent_memory.record_run(make_run(agent="coo"), make_spec())
    content = (tmp_path / f"output/daily/{today}.md").read_text()

    assert content.startswith("---")
    assert f"last_updated: {today}" in content


@pytest.mark.asyncio
async def test_coo_note_contains_section_header_and_result(tmp_path: Path):
    today = time.strftime("%Y-%m-%d", time.gmtime())
    run = make_run(agent="coo", result="My brief result.", trigger="cron")
    await agent_memory.record_run(run, make_spec())
    content = (tmp_path / f"output/daily/{today}.md").read_text()

    assert "## " in content
    assert "UTC" in content
    assert "coo" in content
    assert "cron" in content
    assert "My brief result." in content


@pytest.mark.asyncio
async def test_record_run_returns_filed_true_note_memory():
    out = await agent_memory.record_run(make_run(), make_spec())

    assert out["filed"] is True
    assert "note" in out
    assert "memory" in out
    assert isinstance(out["memory"], dict)


# ── daily-brief agent also goes to daily/ ─────────────────────────────────────

@pytest.mark.asyncio
async def test_daily_brief_uses_daily_path(tmp_path: Path):
    today = time.strftime("%Y-%m-%d", time.gmtime())
    run = make_run(agent="daily-brief", result="Brief content.", trigger="cron")
    out = await agent_memory.record_run(run, make_spec(name="daily-brief"))

    assert out["note"] == f"output/daily/{today}.md"


# ── Non-coo agent → agent log path ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_non_coo_agent_files_to_agent_log(tmp_path: Path):
    today = time.strftime("%Y-%m-%d", time.gmtime())
    run = make_run(agent="inbox-triage", result="Triaged 3 items.", trigger="manual")
    out = await agent_memory.record_run(run, make_spec(name="inbox-triage"))

    expected = f"output/inbox-triage/{today}.md"
    assert out["filed"] is True
    assert out["note"] == expected
    assert (tmp_path / expected).exists()


@pytest.mark.asyncio
async def test_non_coo_note_contains_result(tmp_path: Path):
    today = time.strftime("%Y-%m-%d", time.gmtime())
    run = make_run(agent="planner", result="Plan complete.", trigger="manual")
    await agent_memory.record_run(run, make_spec(name="planner"))
    note = tmp_path / f"output/planner/{today}.md"
    assert "Plan complete." in note.read_text()


# ── Not-success → filed=False ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_failed_status_returns_filed_false():
    run = make_run(status="failed", result="Some output")
    out = await agent_memory.record_run(run, make_spec())

    assert out["filed"] is False
    assert "reason" in out


@pytest.mark.asyncio
async def test_pending_status_returns_filed_false():
    run = make_run(status="pending", result="Some output")
    out = await agent_memory.record_run(run, make_spec())

    assert out["filed"] is False


@pytest.mark.asyncio
async def test_empty_result_returns_filed_false():
    run = make_run(status="success", result="")
    out = await agent_memory.record_run(run, make_spec())

    assert out["filed"] is False


@pytest.mark.asyncio
async def test_none_result_returns_filed_false():
    run = make_run(status="success", result=None)
    out = await agent_memory.record_run(run, make_spec())

    assert out["filed"] is False


# ── RunStatus enum compatibility ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_run_status_enum_treated_as_success(tmp_path: Path):
    """RunStatus.SUCCESS (str-Enum) must be accepted as success."""
    from backend.services.agent_runner import RunStatus

    run = make_run()
    run.status = RunStatus.SUCCESS
    out = await agent_memory.record_run(run, make_spec())

    assert out["filed"] is True


@pytest.mark.asyncio
async def test_run_status_enum_failed_treated_as_not_success():
    from backend.services.agent_runner import RunStatus

    run = make_run(result="output")
    run.status = RunStatus.FAILED
    out = await agent_memory.record_run(run, make_spec())

    assert out["filed"] is False


# ── consolidate_thread raising → filed=True, memory={} ───────────────────────

@pytest.mark.asyncio
async def test_memory_error_still_files(tmp_path: Path, monkeypatch):
    """A failing consolidate_thread must not prevent vault filing."""

    async def _exploding(thread):
        raise RuntimeError("Ollama is down")

    monkeypatch.setattr("backend.services.memory.consolidate_thread", _exploding)

    run = make_run(agent="coo", result="Brief despite memory failure.")
    out = await agent_memory.record_run(run, make_spec())

    assert out["filed"] is True
    assert out["memory"] == {}


@pytest.mark.asyncio
async def test_memory_error_note_still_created(tmp_path: Path, monkeypatch):
    today = time.strftime("%Y-%m-%d", time.gmtime())

    async def _exploding(thread):
        raise ConnectionError("no route to host")

    monkeypatch.setattr("backend.services.memory.consolidate_thread", _exploding)

    await agent_memory.record_run(
        make_run(agent="coo", result="Content here."), make_spec()
    )
    assert (tmp_path / f"output/daily/{today}.md").exists()


# ── Append on second run (same day) ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_second_run_appends_to_same_note(tmp_path: Path):
    today = time.strftime("%Y-%m-%d", time.gmtime())
    spec = make_spec()

    await agent_memory.record_run(make_run(agent="coo", result="First brief.", run_id="r1"), spec)
    await agent_memory.record_run(make_run(agent="coo", result="Second brief.", run_id="r2"), spec)

    content = (tmp_path / f"output/daily/{today}.md").read_text()
    assert "First brief." in content
    assert "Second brief." in content


@pytest.mark.asyncio
async def test_second_run_last_updated_appears_once(tmp_path: Path):
    today = time.strftime("%Y-%m-%d", time.gmtime())
    spec = make_spec()

    await agent_memory.record_run(make_run(agent="coo", result="First.", run_id="r1"), spec)
    await agent_memory.record_run(make_run(agent="coo", result="Second.", run_id="r2"), spec)

    content = (tmp_path / f"output/daily/{today}.md").read_text()
    assert content.count("last_updated:") == 1
