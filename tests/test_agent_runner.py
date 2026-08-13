"""Tests for backend.services.agent_runner.

Tests the AgentRun dataclass, RunStore persistence, and AgentRunner
end-to-end behavior using a mock OllamaService.
"""
import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.ollama import OllamaService
from backend.services.agent_loader import AgentLoader, AgentSpec
from backend.services.agent_runner import (
    AgentRun,
    AgentRunner,
    AgentRunnerError,
    RunStatus,
    RunStore,
)
from backend.services.tools import ToolSpec, build_tools


# === Fixtures ===

@pytest.fixture
def spec_dir(tmp_path: Path) -> Path:
    """A temporary agent directory with a simple spec."""
    agents = tmp_path / "agents"
    agents.mkdir()
    (agents / "echo.md").write_text(
        "---\n"
        "type: agent\n"
        "name: echo\n"
        "description: echoes the context\n"
        "timeout_seconds: 30\n"
        "---\n"
        "You are an echo agent. Repeat what the user said.\n"
    )
    return agents


@pytest.fixture
def loader(spec_dir: Path) -> AgentLoader:
    return AgentLoader(spec_dir)


@pytest.fixture
def store(tmp_path: Path) -> RunStore:
    return RunStore(tmp_path / "runs.jsonl")


def make_ollama_mock(responses: list[dict]) -> OllamaService:
    """Build an OllamaService mock whose .chat() returns successive responses.

    Each response in the list is a dict in Ollama's wire format:
        {"message": {"role": "assistant", "content": "...",
                     "tool_calls": [{"function": {"name": ..., "arguments": ...}}]}}

    We convert each dict into the ChatResponse dataclass the runner expects.
    """
    from backend.ollama import ChatMessage, ChatResponse, ToolCall

    def _to_response(raw: dict) -> ChatResponse:
        raw_msg = raw.get("message", {})
        tcs: list[ToolCall] = []
        for tc in raw_msg.get("tool_calls") or []:
            fn = tc.get("function", {})
            args = fn.get("arguments", {})
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {}
            tcs.append(ToolCall(id=tc.get("id", ""), name=fn.get("name", ""), arguments=args))
        return ChatResponse(
            message=ChatMessage(
                role=raw_msg.get("role", "assistant"),
                content=raw_msg.get("content", ""),
                tool_calls=tcs,
            ),
            model="mock",
            total_duration_ns=0,
            prompt_eval_count=0,
            eval_count=0,
            done_reason="stop",
        )

    svc = MagicMock(spec=OllamaService)
    svc.chat = AsyncMock(side_effect=[_to_response(r) for r in responses])
    return svc


# === AgentRun ===

def test_agent_run_to_dict_includes_status_string():
    run = AgentRun(
        id="abc", agent="x", status=RunStatus.SUCCESS,
        started_at="2026-06-11T00:00:00",
    )
    d = run.to_dict()
    assert d["status"] == "success"
    assert d["id"] == "abc"


# === RunStore ===

def test_store_append_and_list(store: RunStore):
    r1 = AgentRun(id="a", agent="x", status=RunStatus.SUCCESS, started_at="t1")
    r2 = AgentRun(id="b", agent="y", status=RunStatus.FAILED, started_at="t2")
    store.append(r1)
    store.append(r2)
    runs = store.list()
    assert len(runs) == 2
    assert runs[0]["id"] == "a"
    assert runs[1]["id"] == "b"


def test_store_list_filters_by_agent(store: RunStore):
    store.append(AgentRun(id="a", agent="x", status=RunStatus.SUCCESS, started_at="t1"))
    store.append(AgentRun(id="b", agent="y", status=RunStatus.SUCCESS, started_at="t2"))
    only_x = store.list(agent="x")
    assert len(only_x) == 1
    assert only_x[0]["agent"] == "x"


def test_store_list_respects_limit(store: RunStore):
    for i in range(10):
        store.append(AgentRun(id=f"r{i}", agent="x", status=RunStatus.SUCCESS, started_at=f"t{i}"))
    runs = store.list(limit=3)
    assert len(runs) == 3
    # Returns the LAST 3
    assert [r["id"] for r in runs] == ["r7", "r8", "r9"]


# === Durability: crash recovery ===

def test_recover_interrupted_marks_orphaned_runs(store: RunStore):
    # Orphaned: a RUNNING record with no terminal record (process died mid-run).
    store.append(AgentRun(id="orphan", agent="coo", status=RunStatus.RUNNING, started_at="t1"))
    # Complete: RUNNING then a terminal SUCCESS record — must be left alone.
    store.append(AgentRun(id="done", agent="ceo", status=RunStatus.RUNNING, started_at="t2"))
    store.append(AgentRun(id="done", agent="ceo", status=RunStatus.SUCCESS, started_at="t2"))

    recovered = store.recover_interrupted()

    assert recovered == ["orphan"]
    assert store.get("orphan")["status"] == "interrupted"
    assert store.get("orphan")["error"].startswith("interrupted")
    assert store.get("orphan")["finished_at"]                 # stamped
    assert store.get("done")["status"] == "success"           # untouched


def test_recover_interrupted_is_idempotent(store: RunStore):
    store.append(AgentRun(id="orphan", agent="coo", status=RunStatus.RUNNING, started_at="t1"))
    assert store.recover_interrupted() == ["orphan"]
    assert store.recover_interrupted() == []   # no longer RUNNING → nothing to do


def test_store_get_by_id(store: RunStore):
    store.append(AgentRun(id="target", agent="x", status=RunStatus.SUCCESS, started_at="t1"))
    assert store.get("target") is not None
    assert store.get("target")["id"] == "target"
    assert store.get("nonexistent") is None


# === AgentRunner ===

@pytest.mark.asyncio
async def test_runner_returns_error_for_missing_agent(loader, store):
    ollama = make_ollama_mock([])
    runner = AgentRunner(ollama, loader, store)
    with pytest.raises(AgentRunnerError, match="not found"):
        await runner.run("nope")


@pytest.mark.asyncio
async def test_runner_returns_error_for_disabled_agent(spec_dir, store):
    (spec_dir / "off.md").write_text(
        "---\ntype: agent\nname: off\nenabled: false\n---\nDisabled.\n"
    )
    loader = AgentLoader(spec_dir)
    ollama = make_ollama_mock([])
    runner = AgentRunner(ollama, loader, store)
    with pytest.raises(AgentRunnerError, match="disabled"):
        await runner.run("off")


@pytest.mark.asyncio
async def test_runner_completes_when_model_returns_no_tool_calls(loader, store):
    ollama = make_ollama_mock([{
        "message": {"role": "assistant", "content": "Hello.", "tool_calls": None}
    }])
    runner = AgentRunner(ollama, loader, store)
    run = await runner.run("echo", trigger="manual")
    assert run.status == RunStatus.SUCCESS
    assert run.result == "Hello."
    assert run.iterations == 1


@pytest.mark.asyncio
async def test_runner_executes_tool_calls_and_loops(loader, store):
    """The model calls a tool, gets a result, then gives a final answer."""
    # Response 1: tool call to inbox.list_open
    # Response 2: final answer based on the tool result
    responses = [
        {"message": {"role": "assistant", "content": "",
                     "tool_calls": [{
                         "function": {"name": "inbox.list_open", "arguments": {}}
                     }]}},
        {"message": {"role": "assistant", "content": "You have 3 open items.", "tool_calls": None}},
    ]
    inbox = MagicMock()
    inbox.list_all.return_value = []  # no items
    ollama = make_ollama_mock(responses)
    runner = AgentRunner(ollama, loader, store, inbox_service_factory=lambda: inbox)
    run = await runner.run("echo", trigger="manual")
    assert run.status == RunStatus.SUCCESS
    assert "3 open items" in run.result or "0" in run.result  # depends on what model said
    assert run.iterations == 2
    assert len(run.tool_calls) == 1
    assert run.tool_calls[0]["tool"] == "inbox.list_open"


@pytest.mark.asyncio
async def test_runner_handles_unknown_tool_gracefully(loader, store):
    """If the model hallucinates a tool name, the runner doesn't crash."""
    responses = [
        {"message": {"role": "assistant", "content": "",
                     "tool_calls": [{
                         "function": {"name": "fake.tool", "arguments": {}}
                     }]}},
        {"message": {"role": "assistant", "content": "OK, never mind.", "tool_calls": None}},
    ]
    ollama = make_ollama_mock(responses)
    runner = AgentRunner(ollama, loader, store)
    run = await runner.run("echo")
    assert run.status == RunStatus.SUCCESS


@pytest.mark.asyncio
async def test_runner_handles_tool_exception(loader, store):
    """If a tool raises, the error is fed back to the model — it can recover."""
    responses = [
        {"message": {"role": "assistant", "content": "",
                     "tool_calls": [{
                         "function": {"name": "inbox.list_open", "arguments": {}}
                     }]}},
        {"message": {"role": "assistant", "content": "Inbox service is down.", "tool_calls": None}},
    ]
    inbox = MagicMock()
    inbox.list_all.side_effect = RuntimeError("db connection lost")
    ollama = make_ollama_mock(responses)
    runner = AgentRunner(ollama, loader, store, inbox_service_factory=lambda: inbox)
    run = await runner.run("echo")
    assert run.status == RunStatus.SUCCESS
    assert run.iterations == 2


@pytest.mark.asyncio
async def test_runner_marks_timeout_when_deadline_exceeded(loader, store, monkeypatch, tmp_path):
    """If iteration 1 completes quickly but the deadline has passed by iteration 2,
    the runner times out."""
    state = {"now": 0.0}
    def fake_monotonic():
        return state["now"]
    monkeypatch.setattr("time.monotonic", fake_monotonic)
    monkeypatch.setattr("backend.vault.resolve_vault_path", lambda: tmp_path)

    # First call: model returns a tool call (vault.read)
    # The vault.read tool execution bumps time past the deadline
    # Second chat call: never happens because the deadline check fires first
    from backend.ollama import ChatMessage, ChatResponse, ToolCall
    async def chat(*args, **kwargs):
        return ChatResponse(
            message=ChatMessage(
                role="assistant",
                content="",
                tool_calls=[ToolCall(id="t1", name="vault.read", arguments={"path": "x"})],
            ),
            model="mock",
            total_duration_ns=0,
            prompt_eval_count=0,
            eval_count=0,
            done_reason="stop",
        )
    ollama = MagicMock(spec=OllamaService)
    ollama.chat = AsyncMock(side_effect=chat)

    # Wire the runner — vault.read is a built-in tool (no service needed)
    # but we need to patch its underlying time-monotonic check.
    # The handler itself is in tools.py — we patch the function in tools module.
    original_vault_read = None
    from backend.services import tools as tools_mod
    original_vault_read = tools_mod.vault_read

    async def slow_vault_read(*args, **kwargs):
        state["now"] = 1000.0  # jump past deadline
        return await original_vault_read(*args, **kwargs)
    monkeypatch.setattr(tools_mod, "vault_read", slow_vault_read)

    runner = AgentRunner(ollama, AgentLoader(loader.agents_dir), store)
    run = await runner.run("echo")
    assert run.status == RunStatus.TIMEOUT
    assert "timeout" in run.error.lower()


@pytest.mark.asyncio
async def test_hanging_chat_call_is_bounded_by_remaining_budget(spec_dir, tmp_path, monkeypatch):
    """A single ollama.chat() call that never returns must not be allowed to
    block past the run's deadline — asyncio.wait_for cancels it and the run
    is marked TIMEOUT with a clear message, instead of the loop discovering
    the deadline was blown only after the call eventually (uselessly)
    returns."""
    (spec_dir / "echo.md").write_text(
        "---\ntype: agent\nname: echo\ndescription: echoes\ntimeout_seconds: 1\n---\nHi.\n"
    )
    loader = AgentLoader(spec_dir)
    store = RunStore(tmp_path / "runs_hang.jsonl")

    # MIN_CHAT_TIMEOUT_SECONDS would normally floor the per-call budget at
    # 5s; monkeypatch it down so this test doesn't have to wait that long —
    # timeout_seconds: 1 alone gives it a real ~1s budget to cancel within.
    monkeypatch.setattr(AgentRunner, "MIN_CHAT_TIMEOUT_SECONDS", 0.05)

    async def hang(*args, **kwargs):
        await asyncio.sleep(999)

    svc = MagicMock(spec=OllamaService)
    svc.chat = AsyncMock(side_effect=hang)

    monkeypatch.setattr("backend.services.events.publish", lambda ev: None)
    monkeypatch.setattr("backend.services.notify.notify", lambda *a, **kw: None)

    runner = AgentRunner(svc, loader, store)
    run = await runner.run("echo", trigger="manual")

    assert run.status == RunStatus.TIMEOUT
    assert "didn't finish" in run.error


@pytest.mark.asyncio
async def test_runner_persists_run_to_store(loader, store):
    ollama = make_ollama_mock([{
        "message": {"role": "assistant", "content": "done.", "tool_calls": None}
    }])
    runner = AgentRunner(ollama, loader, store)
    run = await runner.run("echo")
    # Both the initial 'running' record and the final record were appended
    runs = store.list(agent="echo")
    assert len(runs) >= 2
    final = [r for r in runs if r["id"] == run.id][-1]
    assert final["status"] == "success"
    assert final["result"] == "done."


# === Autonomy gate + memory write-back ===

@pytest.mark.asyncio
async def test_gated_tool_not_executed_and_in_escalations(loader, store, monkeypatch):
    """A tool classified non-allow must NOT execute and must appear in escalations."""
    from backend.services.autonomy import GateDecision

    def fake_classify(tool, args=None, posture=None):
        if tool == "comms.send":
            return GateDecision(
                decision="gate",
                reason="outward action requires human approval",
                tool=tool,
                side_effect="outward",
            )
        return GateDecision(decision="allow", reason="read-only", tool=tool, side_effect="read")

    monkeypatch.setattr("backend.services.autonomy.classify", fake_classify)

    # The second Ollama response simulates the model adapting after receiving the gated result
    responses = [
        {"message": {"role": "assistant", "content": "",
                     "tool_calls": [{"function": {"name": "comms.send",
                                                  "arguments": {"to": "boss@example.com", "body": "hi"}}}]}},
        {"message": {"role": "assistant", "content": "Gated — awaiting approval.", "tool_calls": None}},
    ]
    ollama = make_ollama_mock(responses)
    runner = AgentRunner(ollama, loader, store)
    run = await runner.run("echo")

    assert run.status == RunStatus.SUCCESS
    assert len(run.escalations) == 1
    assert run.escalations[0]["tool"] == "comms.send"
    assert run.escalations[0]["decision"] == "gate"
    # The tool_calls list carries the gate marker (no "result_preview" from handler)
    gated_tc = [tc for tc in run.tool_calls if tc.get("gate") == "gate"]
    assert len(gated_tc) == 1
    assert gated_tc[0]["tool"] == "comms.send"
    assert "[gate]" in gated_tc[0]["result_preview"]


@pytest.mark.asyncio
async def test_allowed_tool_still_executes_normally(loader, store, monkeypatch):
    """When autonomy.classify returns allow, the handler runs and result is recorded."""
    from backend.services.autonomy import GateDecision

    monkeypatch.setattr(
        "backend.services.autonomy.classify",
        lambda tool, args=None, posture=None: GateDecision(
            decision="allow", reason="read-only", tool=tool, side_effect="read"
        ),
    )

    inbox = MagicMock()
    inbox.list_all.return_value = []

    responses = [
        {"message": {"role": "assistant", "content": "",
                     "tool_calls": [{"function": {"name": "inbox.list_open", "arguments": {}}}]}},
        {"message": {"role": "assistant", "content": "Inbox is empty.", "tool_calls": None}},
    ]
    ollama = make_ollama_mock(responses)
    runner = AgentRunner(ollama, loader, store, inbox_service_factory=lambda: inbox)
    run = await runner.run("echo")

    assert run.status == RunStatus.SUCCESS
    assert run.escalations == []
    assert len(run.tool_calls) == 1
    assert run.tool_calls[0]["tool"] == "inbox.list_open"
    # No gate marker — this was an executed (allowed) call
    assert "gate" not in run.tool_calls[0]


@pytest.mark.asyncio
async def test_record_run_called_on_success(loader, store, monkeypatch):
    """agent_memory.record_run must be awaited exactly once after a successful run."""
    from unittest.mock import AsyncMock

    mock_record = AsyncMock(return_value={"filed": True, "note": "daily/today.md", "memory": {}})
    monkeypatch.setattr("backend.services.agent_memory.record_run", mock_record)

    ollama = make_ollama_mock([{
        "message": {"role": "assistant", "content": "All done.", "tool_calls": None}
    }])
    runner = AgentRunner(ollama, loader, store)
    run = await runner.run("echo")

    assert run.status == RunStatus.SUCCESS
    mock_record.assert_awaited_once()
    called_run, called_spec = mock_record.call_args[0]
    assert called_run is run
    assert called_spec.name == "echo"


@pytest.mark.asyncio
async def test_critic_retry_triggers_one_corrective_rerun(loader, store, monkeypatch):
    """A 'retry' verdict re-runs the agent once with the critic's note, and the
    corrected output is what gets recorded."""
    from unittest.mock import AsyncMock
    from backend.services import critic as critic_mod

    monkeypatch.setenv("AGENT_CRITIC", "1")
    monkeypatch.setattr("backend.services.agent_memory.record_run",
                        AsyncMock(return_value={"filed": True}))

    verdicts = iter([
        critic_mod.CriticVerdict("retry", "missing the money section"),
        critic_mod.CriticVerdict("pass", "complete now"),
    ])

    async def fake_verify(goal, output, agent=""):
        return next(verdicts)

    monkeypatch.setattr("backend.services.agent_runner.critic.verify", fake_verify)

    # First attempt, then the corrective re-run produces the final answer.
    ollama = make_ollama_mock([
        {"message": {"role": "assistant", "content": "first attempt"}},
        {"message": {"role": "assistant", "content": "corrected answer"}},
    ])
    runner = AgentRunner(ollama, loader, store)
    run = await runner.run("echo")

    assert run.status == RunStatus.SUCCESS
    assert run.result == "corrected answer"          # the retry's output won
    assert run.critic["verdict"] == "pass"           # re-verified after retry


@pytest.mark.asyncio
async def test_critic_escalate_flags_run(loader, store, monkeypatch):
    """An 'escalate' verdict keeps the output but records the critic verdict."""
    from unittest.mock import AsyncMock
    from backend.services import critic as critic_mod

    monkeypatch.setenv("AGENT_CRITIC", "1")
    monkeypatch.setattr("backend.services.agent_memory.record_run",
                        AsyncMock(return_value={"filed": True}))

    async def fake_verify(goal, output, agent=""):
        return critic_mod.CriticVerdict("escalate", "contradicts known net worth", True)

    monkeypatch.setattr("backend.services.agent_runner.critic.verify", fake_verify)

    ollama = make_ollama_mock([{"message": {"role": "assistant", "content": "net worth is +$1M"}}])
    runner = AgentRunner(ollama, loader, store)
    run = await runner.run("echo")

    assert run.status == RunStatus.SUCCESS
    assert run.result == "net worth is +$1M"         # output kept, not blocked
    assert run.critic["verdict"] == "escalate"
    assert run.critic["contradicts_memory"] is True


@pytest.mark.asyncio
async def test_record_run_not_called_on_failure(loader, store, monkeypatch):
    """agent_memory.record_run must NOT be called when the run fails."""
    from unittest.mock import AsyncMock

    mock_record = AsyncMock(return_value={"filed": False, "reason": "not success"})
    monkeypatch.setattr("backend.services.agent_memory.record_run", mock_record)

    # Patch _execute to raise so the run ends in FAILED state
    async def boom(*args, **kwargs):
        raise RuntimeError("injected failure")

    monkeypatch.setattr(
        "backend.services.agent_runner.AgentRunner._execute",
        boom,
    )

    ollama = make_ollama_mock([])
    runner = AgentRunner(ollama, loader, store)
    run = await runner.run("echo")

    assert run.status == RunStatus.FAILED
    mock_record.assert_not_awaited()


# === Event publishing + notifications ===

@pytest.mark.asyncio
async def test_events_published_and_notify_called_on_success(loader, store, monkeypatch):
    """events.publish gets started+finished events; notify.notify called on success."""
    from unittest.mock import AsyncMock as _AsyncMock

    published: list[dict] = []
    notified: list[tuple] = []

    monkeypatch.setattr(
        "backend.services.agent_memory.record_run",
        _AsyncMock(return_value={}),
    )
    monkeypatch.setattr(
        "backend.services.events.publish",
        lambda ev: published.append(dict(ev)),
    )
    monkeypatch.setattr(
        "backend.services.notify.notify",
        lambda title, body, **kw: notified.append((title, body)),
    )

    ollama = make_ollama_mock([{
        "message": {"role": "assistant", "content": "Done!", "tool_calls": None}
    }])
    runner = AgentRunner(ollama, loader, store)
    run = await runner.run("echo", trigger="manual")

    assert run.status == RunStatus.SUCCESS

    phases = [(e["type"], e.get("phase")) for e in published]
    assert ("agent.run", "started") in phases, f"no started event in {phases}"
    assert ("agent.run", "finished") in phases, f"no finished event in {phases}"

    finished = next(e for e in published if e.get("phase") == "finished")
    assert finished["status"] == "success"
    assert finished["run_id"] == run.id
    assert finished["agent"] == "echo"

    started = next(e for e in published if e.get("phase") == "started")
    assert started["agent"] == "echo"
    assert started["run_id"] == run.id

    # notify called at least once with a success title (✓ prefix)
    assert notified, "notify was never called"
    assert any(title.startswith("✓") for title, _ in notified), (
        f"no success notification; got: {notified}"
    )


# === Retry + fallback tests ===

@pytest.fixture
def spec_dir_with_fallback(tmp_path: Path) -> Path:
    """A temporary agent directory with a spec that has fallback_model set."""
    agents = tmp_path / "agents_fb"
    agents.mkdir()
    (agents / "echo.md").write_text(
        "---\n"
        "type: agent\n"
        "name: echo\n"
        "description: echoes the context\n"
        "timeout_seconds: 30\n"
        "fallback_model: anthropic:claude-haiku-4.5\n"
        "---\n"
        "You are an echo agent. Repeat what the user said.\n"
    )
    return agents


@pytest.mark.asyncio
async def test_fallback_used_when_ollama_always_fails(spec_dir_with_fallback, tmp_path, monkeypatch):
    """When ollama.chat always raises ConnectError and fallback_model is set,
    the run ends SUCCESS with the fallback answer."""
    import httpx
    from backend.llm_hub import ChatResult
    from backend.services.agent_loader import AgentLoader
    from backend.services.agent_runner import RunStore

    store = RunStore(tmp_path / "runs_fb.jsonl")
    loader = AgentLoader(spec_dir_with_fallback)

    # Ollama always fails
    svc = MagicMock(spec=OllamaService)
    svc.chat = AsyncMock(side_effect=httpx.ConnectError("refused"))

    # Fake cloud backend
    fake_result = MagicMock()
    fake_result.content = "fallback answer"

    fake_backend = MagicMock()
    fake_backend.chat = AsyncMock(return_value=fake_result)

    monkeypatch.setattr("backend.llm_hub.get_backend", lambda name: fake_backend)
    monkeypatch.setattr("backend.services.agent_memory.record_run", AsyncMock(return_value={}))
    monkeypatch.setattr("backend.services.events.publish", lambda ev: None)
    monkeypatch.setattr("backend.services.notify.notify", lambda *a, **kw: None)

    runner = AgentRunner(svc, loader, store)
    run = await runner.run("echo", trigger="manual")

    assert run.status == RunStatus.SUCCESS
    assert run.result == "fallback answer"
    assert run.error is not None and "degraded" in run.error
    assert "claude-haiku-4.5" in (run.error or "")


@pytest.mark.asyncio
async def test_retry_succeeds_after_one_transient_error(loader, store, monkeypatch):
    """When ollama.chat fails once then succeeds, the run ends SUCCESS (retry worked)."""
    import httpx
    from backend.ollama import ChatMessage, ChatResponse

    good_response = ChatResponse(
        message=ChatMessage(role="assistant", content="retry worked", tool_calls=[]),
        model="mock",
        total_duration_ns=0,
        prompt_eval_count=0,
        eval_count=0,
        done_reason="stop",
    )

    svc = MagicMock(spec=OllamaService)
    svc.chat = AsyncMock(side_effect=[httpx.ConnectError("transient"), good_response])

    monkeypatch.setattr("backend.services.agent_memory.record_run", AsyncMock(return_value={}))
    monkeypatch.setattr("backend.services.events.publish", lambda ev: None)
    monkeypatch.setattr("backend.services.notify.notify", lambda *a, **kw: None)

    runner = AgentRunner(svc, loader, store)
    run = await runner.run("echo", trigger="manual")

    assert run.status == RunStatus.SUCCESS
    assert run.result == "retry worked"
    # chat was called twice: once failed, once succeeded
    assert svc.chat.call_count == 2


@pytest.mark.asyncio
async def test_run_fails_when_ollama_always_fails_and_no_fallback(loader, store, monkeypatch):
    """When ollama.chat always fails and no fallback_model is set, run ends FAILED."""
    import httpx

    svc = MagicMock(spec=OllamaService)
    svc.chat = AsyncMock(side_effect=httpx.ConnectError("refused"))

    monkeypatch.setattr("backend.services.events.publish", lambda ev: None)
    monkeypatch.setattr("backend.services.notify.notify", lambda *a, **kw: None)

    runner = AgentRunner(svc, loader, store)
    run = await runner.run("echo", trigger="manual")

    assert run.status == RunStatus.FAILED
    assert run.result is None


# === Live integration test (skipped by default) ===

@pytest.mark.skipif(
    not __import__("os").environ.get("OLLAMA_LIVE_TEST"),
    reason="live Ollama test — set OLLAMA_LIVE_TEST=1 to enable",
)
@pytest.mark.asyncio
async def test_runner_live_against_ollama(loader, store):
    """End-to-end against a real Ollama with a real agent spec.

    Opt-in only. Set OLLAMA_LIVE_TEST=1 to run. Without it, returns
    immediately so it doesn't hang the test suite in sandboxes where
    Ollama might not be reachable.
    """
    import os
    if not os.environ.get("OLLAMA_LIVE_TEST"):
        return  # explicit early-return
    from backend.vault import agentic_os_dir
    agents = agentic_os_dir() / "agents"
    if not (agents / "daily-brief.md").exists():
        return
    ollama = OllamaService()
    loader = AgentLoader(agents)
    runner = AgentRunner(ollama, loader, store)
    run = await runner.run("daily-brief", trigger="manual")
    assert run.status in (RunStatus.SUCCESS, RunStatus.TIMEOUT)
    # Result should mention something — not empty
    assert run.result and len(run.result) > 20
