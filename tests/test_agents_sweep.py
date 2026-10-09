"""Regression tests for the agents-area bug sweep (F72-F152)."""
from __future__ import annotations

import asyncio
import json
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

GOOD = "---\ntype: agent\nname: good\nschedule: \"0 7 * * *\"\n---\nHi.\n"
BAD = "---\ntype: agent\nname: bad\nschedule: \"every day\"\n---\nHi.\n"


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("ACADEMIC_OS_DATA", str(tmp_path))
    d = tmp_path / "agents"
    d.mkdir(parents=True)
    (d / "good.md").write_text(GOOD)
    with TestClient(__import__("backend.app", fromlist=["app"]).app) as c:
        c.root = tmp_path
        yield c


# F73 -------------------------------------------------------------------------
def test_malformed_agent_does_not_break_list_or_rescan(client):
    (client.root / "agents" / "bad.md").write_text(BAD)
    r = client.get("/api/agents")
    assert r.status_code == 200
    assert {a["name"] for a in r.json()["agents"]} == {"good"}
    client.app.state.agent_scheduler.rescan()  # must not raise
    assert "good" in client.app.state.agent_scheduler.job_names()


# F77 -------------------------------------------------------------------------
def test_get_resolves_by_frontmatter_name(client):
    (client.root / "agents" / "my-agent.md").write_text(
        "---\ntype: agent\nname: Daily Brief\n---\nHi.\n")
    assert client.get("/api/agents/Daily Brief").status_code == 200
    assert client.get("/api/agents/my-agent").status_code == 200


# F74 / F75 -------------------------------------------------------------------
@pytest.mark.asyncio
async def test_set_schedule_edits_real_spec_path(client):
    from backend.services.agent_admin import set_schedule
    res = await set_schedule("good", schedule="0 9 * * 1")
    assert res["ok"] is True, res
    assert "0 9 * * 1" in (client.root / "agents" / "good.md").read_text()
    assert (await set_schedule("../good", schedule="* * * * *"))["ok"] is False
    assert (await set_schedule("nope", enabled=False))["error"] == "agent not found"


@pytest.mark.asyncio
async def test_execute_item_failed_result_is_not_executed():
    from backend.services.approvals import execute_item
    tool = SimpleNamespace(name="t", handler=AsyncMock(return_value={"error": "bad_type"}))
    out = await execute_item({"tool": "t", "args": {}}, [tool])
    assert out["executed"] is False and out["failed"] is True
    assert out["reason"] == "bad_type"
    tool.handler = AsyncMock(return_value={"ok": False, "error": "x"})
    assert (await execute_item({"tool": "t"}, [tool]))["executed"] is False
    tool.handler = AsyncMock(return_value={"ok": True})
    assert (await execute_item({"tool": "t"}, [tool]))["executed"] is True


def test_failed_approval_stays_pending(client, monkeypatch, tmp_path):
    from backend.services import approvals
    # module-level paths are bound at import time: pin them to tmp
    monkeypatch.setattr(approvals, "DECISIONS_PATH", tmp_path / "dec.jsonl")
    monkeypatch.setattr(approvals, "EXECUTIONS_PATH", tmp_path / "exec.jsonl")
    run = {"id": "r1", "agent": "good", "status": "success", "started_at": "2026-01-01T00:00:00",
           "escalations": [{"tool": "academics.add_application",
                            "args": {"name": "X", "type": "scholarships"}, "reason": "gate"}]}
    client.app.state.run_store.path.parent.mkdir(parents=True, exist_ok=True)
    with client.app.state.run_store.path.open("a") as f:
        f.write(json.dumps(run) + "\n")
    r = client.post("/api/approvals/decide", json={"item_id": "r1:0", "decision": "approved"})
    assert r.status_code == 200
    ex = r.json()["exec_result"]
    assert ex["executed"] is False and ex["failed"] is True
    pend = client.get("/api/approvals").json()["pending"]
    assert any(p["id"] == "r1:0" for p in pend)
    assert not approvals.was_executed("r1:0")


# F83 -------------------------------------------------------------------------
def test_list_pending_scans_whole_log(monkeypatch, tmp_path):
    from backend.services import approvals
    monkeypatch.setattr(approvals, "DECISIONS_PATH", tmp_path / "dec.jsonl")
    runs = [{"id": "old", "agent": "a", "started_at": "2026-01-01",
             "escalations": [{"tool": "x", "args": {}}]}]
    for i in range(60):
        runs.append({"id": f"n{i}", "agent": "a", "started_at": "2026-02-01", "escalations": []})

    class S:
        def list(self, agent=None, limit=50):
            return runs[-limit:]
    assert "old:0" in [p["id"] for p in approvals.list_pending(S())]


# F82 -------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_critic_retry_does_not_duplicate_escalations_or_effects(tmp_path, monkeypatch):
    from backend.ollama import ChatMessage, ChatResponse, ToolCall
    from backend.services import critic as critic_mod
    from backend.services.agent_loader import AgentLoader
    from backend.services.agent_runner import AgentRunner, RunStore, RunStatus

    agents = tmp_path / "agents"
    agents.mkdir()
    (agents / "w.md").write_text(
        "---\ntype: agent\nname: w\ntools:\n  - inbox.add\n---\nDo it.\n")
    monkeypatch.setenv("AGENT_CRITIC", "1")
    monkeypatch.setattr("backend.services.agent_memory.record_run",
                        AsyncMock(return_value={"filed": True}))
    verdicts = iter([critic_mod.CriticVerdict("retry", "again"),
                     critic_mod.CriticVerdict("pass", "ok")])

    async def fake_verify(goal, output, agent=""):
        return next(verdicts)
    monkeypatch.setattr("backend.services.agent_runner.critic.verify", fake_verify)

    def resp(content="", calls=()):
        return ChatResponse(
            message=ChatMessage(role="assistant", content=content, tool_calls=[
                ToolCall(id=f"c{i}", name=n, arguments=a) for i, (n, a) in enumerate(calls)]),
            model="m", total_duration_ns=0, prompt_eval_count=0, eval_count=0, done_reason="stop")
    esc = ("comms.send", {"to": "a@b.c"})
    add = ("inbox.add", {"text": "remember this"})
    seq = [resp("", [esc, add]), resp("first"), resp("", [esc, add]), resp("second")]
    ollama = MagicMock()
    ollama.chat = AsyncMock(side_effect=seq)
    inbox = MagicMock()
    runner = AgentRunner(ollama, AgentLoader(agents), RunStore(tmp_path / "r.jsonl"),
                         inbox_service_factory=lambda: inbox)
    run = await runner.run("w")
    assert run.status == RunStatus.SUCCESS
    assert len(run.escalations) == 1
    assert inbox.add.call_count == 1


# F86 -------------------------------------------------------------------------
def test_runner_context_uses_local_date_not_utc():
    import inspect
    from backend.services import agent_runner
    src = inspect.getsource(agent_runner.AgentRunner._execute)
    assert "gmtime" not in src


# F87 -------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_reminder_sets_day_one_before_month(monkeypatch):
    import backend.services.reminders as rem
    monkeypatch.setattr(rem.sys, "platform", "darwin")
    seen = {}

    def fake_run(cmd, **kw):
        seen["script"] = cmd[2]
        return SimpleNamespace(returncode=0, stdout="x", stderr="")
    monkeypatch.setattr(rem.subprocess, "run", fake_run)
    await rem.create_reminder("t", "2026-11-15")
    s = seen["script"]
    assert s.index("set day of dueDate to 1") < s.index("set month of dueDate to 11")
    assert s.index("set month of dueDate to 11") < s.index("set day of dueDate to 15")


# F88 -------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_add_application_rejects_non_iso_deadline(tmp_path):
    from backend.services import academics_tools as at
    at.reset_services()
    for bad in ("Dec 5", "12/05/2026", "tomorrow"):
        assert (await at.add_application("X", deadline=bad))["error"] == "bad_deadline"
    assert (await at.add_application("X", deadline="2026-12-05"))["ok"] is True
    assert (await at.add_application("Y"))["ok"] is True
    at.reset_services()


# F90 -------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_events_from_foreign_thread_wake_loop():
    from backend.services import events
    q = events.subscribe()
    try:
        threading.Timer(0.2, lambda: events.publish({"type": "x"})).start()
        got = await asyncio.wait_for(q.get(), timeout=2)
        assert got["type"] == "x"
    finally:
        events.unsubscribe(q)


# F81 -------------------------------------------------------------------------
def test_inbox_concurrent_add_and_mark_done_lose_nothing(tmp_path):
    from backend.services.inbox import InboxService
    svc = InboxService(tmp_path)
    seeded = [svc.add(f"seed {i}") for i in range(150)]

    def adder():
        for i in range(60):
            svc.add(f"new {i}")

    def doner():
        for it in seeded:
            svc.mark_done(it.id)
    ts = [threading.Thread(target=adder), threading.Thread(target=doner)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert len(svc.list_all()) == 210


# F80 -------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_memory_compact_sees_notes_written_by_memory_writer(monkeypatch, tmp_path):
    monkeypatch.setattr("backend.vault.resolve_vault_path", lambda: tmp_path)
    from backend.services import memory_compact, memory_writer
    from backend.services.memory_types import MemoryItem
    assert memory_compact._MEMORY_BASE == memory_writer._MEMORY_BASE
    item = MemoryItem(kind="fact", subject="chem", body="Chem final on 2026-12-10",
                      tags=[], source_thread="t", ts="2026-10-09T00:00:00Z", confidence=1.0)
    await memory_writer.file_item(item)
    res = await memory_compact.compact_all()
    assert "facts.md" in res["files"]


# F79 -------------------------------------------------------------------------
def test_forget_scrubs_log_and_tombstones(client):
    from backend.services import memory_index
    from backend.services.memory_types import MemoryItem
    from backend.vault import resolve_vault_path
    item = MemoryItem(kind="fact", subject="chem", body="Chem final on 2026-12-10",
                      tags=[], source_thread="t", ts="2026-10-09T00:00:00Z", confidence=1.0)
    iid = memory_index.upsert_item(item)
    log = resolve_vault_path() / "notes" / "memory" / "log" / "2026-10-09.md"
    log.parent.mkdir(parents=True)
    log.write_text("- Chem final on 2026-12-10\n- other\n")
    assert client.delete(f"/api/memory/items/{iid}").status_code == 200
    assert "Chem final" not in log.read_text()
    assert memory_index.is_forgotten(item)


# F72 / F78 -------------------------------------------------------------------
def test_chat_stream_sends_thread_history_and_consolidates(client, monkeypatch):
    import backend.app as appmod
    seen = []

    class FakeBackend:
        async def chat_stream(self, messages, model=""):
            seen.append([(m.role, m.content) for m in messages if m.role != "system"])
            yield {"delta": "ok"}
            yield {"done": True, "message": {"role": "assistant", "content": "ok",
                                              "backend": "ollama", "model": "m",
                                              "tokens": 1, "elapsed_ms": 1}}
    monkeypatch.setattr(appmod, "get_backend", lambda n: FakeBackend())
    consolidated = []

    async def fake_cons(tid):
        consolidated.append(tid)
    monkeypatch.setattr(appmod, "_consolidate_safe", fake_cons)
    monkeypatch.setenv("MEMORY_CONSOLIDATION", "1")

    def turn(text, tid=None):
        r = client.post("/api/llms/chat/stream", json={
            "backend": "ollama", "model": "m", "thread_id": tid,
            "messages": [{"role": "user", "content": text}]})
        done = [json.loads(l[6:]) for l in r.text.splitlines() if l.startswith("data: ")][-1]
        return done["thread_id"]
    tid = turn("My exam is on Friday")
    turn("explain that more simply", tid)
    assert seen[1] == [("user", "My exam is on Friday"), ("assistant", "ok"),
                       ("user", "explain that more simply")]
    assert consolidated == [tid, tid]


# F141 ------------------------------------------------------------------------
def test_assignment_item_uses_course_name():
    from backend.services.routines import _assignment_to_item
    a = SimpleNamespace(id="a", title="Lab", due="2026-10-11", course_id="d583")
    assert _assignment_to_item(a, {"d583": "Chem 101"})["context"] == "Chem 101"
    assert _assignment_to_item(a)["context"] == "d583"
