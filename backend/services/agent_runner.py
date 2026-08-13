"""Agent runner — executes agent definitions using Ollama + tools.

This is the workhorse. The runner:
1. Loads an agent spec (cached in the registry)
2. Builds the tool list (services -> ToolSpec)
3. Sends the system prompt + available tools to Ollama
4. Loops on tool calls: model returns tool_call -> runner executes ->
   feeds result back to model -> repeat until model returns a final
   message or the iteration cap is hit
5. Records the run (id, agent, status, started/finished, result, error)
   in Agentic OS/data/agents/runs.jsonl

Why iteration cap: the model can in principle loop forever calling
tools. Cap at 8 iterations per run (a sensible default for gemma4).

Why use Ollama's tool format: gemma4 supports it natively. We pass the
tool schema, the model decides which (if any) tools to call, returns
the call as JSON, we execute and feed the result back.
"""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Optional

import httpx

from backend.ollama import OllamaService
from backend.services import (
    autonomy, agent_memory, events, notify, critic, trace, trajectory_memory,
)
from backend.services.agent_loader import AgentLoader, AgentSpec
from backend.services.tools import (
    ToolSpec,
    build_tools,
    get_tool_by_name,
    tools_to_ollama_schema,
)
from backend.vault import agentic_os_dir


# === Status + run record ===

class RunStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"  # crash-orphaned: process exited mid-run


@dataclass
class AgentRun:
    """One execution of one agent."""
    id: str
    agent: str
    status: RunStatus
    started_at: str
    finished_at: Optional[str] = None
    result: Optional[str] = None  # final model output
    error: Optional[str] = None
    iterations: int = 0
    tool_calls: list[dict] = field(default_factory=list)
    duration_seconds: float = 0.0
    trigger: Optional[str] = None  # manual | cron | vault_event:<path>:<kind>
    escalations: list[dict] = field(default_factory=list)
    critic: Optional[dict] = None  # verifier verdict: {verdict, reason, contradicts_memory}

    def to_dict(self) -> dict:
        d = asdict(self)
        d["status"] = self.status.value
        return d


# === Run store ===

class RunStore:
    """Append-only log of agent runs. JSONL at Agentic OS/data/agents/runs.jsonl."""

    def __init__(self, store_path: Optional[Path] = None):
        if store_path is None:
            store_path = agentic_os_dir() / "data" / "agents" / "runs.jsonl"
        self.path = Path(store_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, run: AgentRun) -> None:
        with self.path.open("a") as f:
            f.write(json.dumps(run.to_dict()) + "\n")

    def list(self, agent: Optional[str] = None, limit: int = 50) -> list[dict]:
        if not self.path.exists():
            return []
        out: list[dict] = []
        with self.path.open() as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if agent is None or r.get("agent") == agent:
                    out.append(r)
        return out[-limit:]

    def get(self, run_id: str) -> Optional[dict]:
        # A run is appended twice (RUNNING first, then the final record). Return
        # the LAST match so callers see the finished state, not the initial one.
        found: Optional[dict] = None
        for r in self.list(limit=10_000):
            if r.get("id") == run_id:
                found = r
        if found is not None:
            return found
        return None

    def recover_interrupted(self) -> list[str]:
        """Durability: reconcile runs orphaned by a crash.

        A run writes a RUNNING record, then a terminal record. If the process
        dies between the two, the run is stuck as eternal "running" — polluting
        the UI, activity feed, and approval dedup. On startup we fold the log to
        each run's latest status; any still RUNNING gets a terminal INTERRUPTED
        record appended (preserving the original fields). Idempotent: a second
        call finds nothing, since recovered runs are no longer RUNNING.

        Returns the list of run ids recovered.
        """
        latest: dict[str, dict] = {}
        for r in self.list(limit=1_000_000):
            rid = r.get("id")
            if rid:
                latest[rid] = r
        now = datetime.now().isoformat(timespec="microseconds")
        recovered: list[str] = []
        for rid, rec in latest.items():
            if rec.get("status") == RunStatus.RUNNING.value:
                fixed = dict(rec)
                fixed["status"] = RunStatus.INTERRUPTED.value
                fixed["finished_at"] = now
                fixed["error"] = "interrupted — process exited before the run finished"
                with self.path.open("a") as f:
                    f.write(json.dumps(fixed) + "\n")
                recovered.append(rid)
        return recovered


# === Model routing ===

# Non-ollama backend prefixes are not routed through the local tool-loop yet
# (Phase 2 is local-first). They fall back to the OllamaService default.
_NON_OLLAMA_BACKENDS = {
    "anthropic", "openai", "claude", "codex", "gemini", "droid", "cursor", "hermes",
}


def _resolve_ollama_model(spec_model: Optional[str]) -> Optional[str]:
    """Map an agent spec's `model` field to an Ollama model name for chat().

    - "ollama:qwen3:30b-a3b" -> "qwen3:30b-a3b"
    - "gemma4:latest" (bare) -> "gemma4:latest" (assumed ollama)
    - "anthropic:claude-..." -> None (not routed; use service default)
    - None/"" -> None (use service default)
    """
    if not spec_model:
        return None
    m = spec_model.strip()
    if m.startswith("ollama:"):
        return m[len("ollama:"):] or None
    prefix = m.split(":", 1)[0] if ":" in m else ""
    if prefix in _NON_OLLAMA_BACKENDS:
        return None
    return m


# === Runner ===

class AgentRunner:
    """Runs an agent end-to-end. Yields control while the LLM thinks.

    Services are passed as callables (factories) so the runner can resolve
    them lazily. This lets the calendar service start on-demand (so the
    app boots even when CalDAV creds are missing) and the runner gets a
    working service the moment an agent actually needs it.
    """

    DEFAULT_MAX_ITERATIONS = 8
    # Floor for the per-call chat budget (see _execute): even when the run's
    # deadline is nearly up, give the model at least this long to respond
    # rather than cancelling it almost instantly.
    MIN_CHAT_TIMEOUT_SECONDS = 5.0

    def __init__(
        self,
        ollama: OllamaService,
        agent_loader: AgentLoader,
        run_store: RunStore,
        calendar_service_factory=None,
        inbox_service_factory=None,
        browser_service_factory=None,
    ):
        self.ollama = ollama
        self.agent_loader = agent_loader
        self.run_store = run_store
        self._service_factories = {
            "calendar": calendar_service_factory,
            "inbox": inbox_service_factory,
            "browser": browser_service_factory,
        }
        # Track in-flight tasks for cancellation
        self._in_flight: dict[str, asyncio.Task] = {}

    def _build_tools(self) -> list[ToolSpec]:
        # Resolve services via factories (lazy). If a factory is None or
        # raises, that tool is simply not included.
        services = {}
        for name, factory in self._service_factories.items():
            if factory is None:
                continue
            try:
                services[name] = factory()
            except Exception:
                services[name] = None
        return build_tools(
            calendar_service=services.get("calendar"),
            inbox_service=services.get("inbox"),
            browser_service=services.get("browser"),
        )

    async def _chat_with_retry(self, messages, tools, agent_model, retries=2):
        """Call ollama.chat with exponential-backoff retries on transient errors."""
        delay = 0.5
        last = None
        for attempt in range(retries + 1):
            try:
                return await self.ollama.chat(messages=messages, tools=tools, model=agent_model)
            except (httpx.HTTPError, httpx.ConnectError, httpx.TimeoutException, asyncio.TimeoutError) as e:
                last = e
                if attempt < retries:
                    await asyncio.sleep(delay)
                    delay *= 2.5
        raise last

    @staticmethod
    def _resolve_fallback(fallback_model):
        """Parse "anthropic:claude-haiku-4.5" -> ("claude", "claude-haiku-4.5")."""
        if not fallback_model:
            return None
        prefix, _, rest = fallback_model.partition(":")
        alias = {"anthropic": "claude", "openai": "codex"}.get(prefix, prefix)
        return (alias, rest or "")

    async def _fallback_complete(self, spec, messages) -> "str | None":
        """One degraded best-effort completion via the hub (no tools)."""
        res = self._resolve_fallback(spec.fallback_model)
        if not res:
            return None
        backend_name, model = res
        try:
            from backend.llm_hub import get_backend, ChatMessage as HubMsg
            b = get_backend(backend_name)
            hub_msgs = [
                HubMsg(role=getattr(m, "role", "user"), content=getattr(m, "content", "") or "")
                for m in messages
            ]
            out = await b.chat(hub_msgs, model=model)
            return (out.content or "").strip() or None
        except Exception:
            return None

    async def run(
        self,
        agent_name: str,
        trigger: str = "manual",
        trigger_context: Optional[dict] = None,
        background: bool = False,
    ) -> AgentRun:
        """Run an agent. Returns the AgentRun record (also appended to store).

        background=False (default): await the full run, return the finished record
        (used by cron, tests, and any caller that wants the result).
        background=True: append the RUNNING record, schedule the lifecycle as a
        detached task, and return the RUNNING record immediately. The caller polls
        /api/agents/runs/{id} for completion. Used by the HTTP run endpoint so the
        request doesn't block for the whole LLM tool-loop.
        """
        spec = self.agent_loader.get(agent_name)
        if spec is None:
            raise AgentRunnerError(f"agent not found: {agent_name}")
        if not spec.enabled:
            raise AgentRunnerError(f"agent is disabled: {agent_name}")

        run = AgentRun(
            id=uuid.uuid4().hex[:12],
            agent=agent_name,
            status=RunStatus.RUNNING,
            started_at=datetime.now().isoformat(timespec="microseconds"),
            trigger=trigger,
        )
        self.run_store.append(run)
        try:
            events.publish({"type": "agent.run", "phase": "started", "agent": agent_name, "run_id": run.id})
        except Exception:
            pass
        if background:
            self._in_flight[run.id] = asyncio.create_task(
                self._lifecycle(spec, run, trigger_context, reraise_cancel=False)
            )
            return run
        await self._lifecycle(spec, run, trigger_context, reraise_cancel=True)
        return run

    async def _lifecycle(
        self,
        spec: AgentSpec,
        run: AgentRun,
        trigger_context: Optional[dict],
        reraise_cancel: bool,
    ) -> None:
        """Execute the run to completion: tool-loop, finalize, write-back, persist.

        Shared by the sync and background paths of run()."""
        run_task = asyncio.create_task(self._execute(spec, run, trigger_context))
        self._in_flight[run.id] = run_task
        try:
            await run_task
        except asyncio.CancelledError:
            run.status = RunStatus.CANCELLED
            if reraise_cancel:
                raise
        except Exception as e:
            run.status = RunStatus.FAILED
            run.error = str(e)
        finally:
            run.finished_at = datetime.now().isoformat(timespec="microseconds")
            run.duration_seconds = (
                datetime.fromisoformat(run.finished_at).timestamp()
                - datetime.fromisoformat(run.started_at).timestamp()
            )
            self._in_flight.pop(run.id, None)
        # Critic gate (blueprint §2.2): verify a successful output BEFORE it is
        # written back to memory. Fail-open — never blocks the run.
        if run.status == RunStatus.SUCCESS and run.result:
            await self._verify(spec, run, trigger_context)
        if run.status == RunStatus.SUCCESS:
            try:
                await agent_memory.record_run(run, spec)
            except Exception as wb_err:
                print(f"[agent_runner] write-back failed for {run.id}: {wb_err}")
        self.run_store.append(run)  # final record
        # Unified trajectory trace (blueprint §2.3 / roadmap B1): fold the
        # finished run into one canonical record for the eval harness (B2) and
        # trajectory memory (B3). record_trace is fail-open — never disrupts.
        trace.record_trace(run, spec)
        # Trajectory memory (blueprint §2.4 / roadmap B3): graduate a
        # critic-passed run into the few-shot corpus. No-op unless
        # AGENT_TRAJECTORY_MEMORY is set; fail-open either way (outer guard keeps
        # this consistent with the write-back/events handling above).
        try:
            await trajectory_memory.store_trajectory(run, spec)
        except Exception as _te:  # noqa: BLE001
            print(f"[agent_runner] trajectory store skipped: {_te}")
        try:
            events.publish({
                "type": "agent.run",
                "phase": "finished",
                "agent": run.agent,
                "run_id": run.id,
                "status": run.status.value,
                "escalations": len(run.escalations),
                "summary": (run.result or run.error or "")[:120],
            })
            if run.status == RunStatus.SUCCESS:
                notify.notify(f"✓ {run.agent}", (run.result or "")[:140])
            elif run.status in (RunStatus.FAILED, RunStatus.TIMEOUT):
                notify.notify(f"⚠ {run.agent} failed", (run.error or "")[:140])
            if run.escalations:
                notify.notify("● Approval needed", f"{run.agent}: {len(run.escalations)} action(s)")
                events.publish({
                    "type": "approval",
                    "agent": run.agent,
                    "tool": (run.escalations[0].get("tool", "") if run.escalations else ""),
                    "count": len(run.escalations),
                })
        except Exception:
            pass

    async def _execute(
        self,
        spec: AgentSpec,
        run: AgentRun,
        trigger_context: Optional[dict],
        critic_note: Optional[str] = None,
    ) -> None:
        """The actual work: call Ollama, loop on tool calls, return final.

        *critic_note* (set on a critic-triggered retry) is injected as a final
        corrective instruction so the model addresses what the reviewer flagged.
        """
        from backend.ollama import ChatMessage, ToolCall

        tools = self._build_tools()
        ollama_tools = tools_to_ollama_schema(tools)

        # Compose the message history as ChatMessage objects (not raw dicts —
        # the refactored OllamaService.chat() takes list[ChatMessage]).
        # Inject the real date so the model never guesses it (local models have
        # no notion of "today"). Applies to every agent's reasoning + output.
        _today = time.strftime("%Y-%m-%d", time.gmtime())
        _hhmm = time.strftime("%H:%M", time.gmtime())
        _date_ctx = (
            f"\n\n[Context: today is {_today} (UTC), current time {_hhmm} UTC. "
            f"Use this for all date reasoning; never guess the date.]"
        )
        messages: list[ChatMessage] = [
            ChatMessage(role="system", content=spec.prompt + _date_ctx),
        ]
        # Trajectory memory (blueprint §2.4 / roadmap B3): condition on similar
        # past successes as few-shot guidance. No-op unless
        # AGENT_TRAJECTORY_MEMORY is set; fail-open so retrieval never blocks.
        try:
            _fewshot = await trajectory_memory.maybe_inject(
                getattr(spec, "description", "") or spec.name,
                agent=spec.name,
            )
            if _fewshot:
                messages.append(ChatMessage(role="system", content=_fewshot))
        except Exception as _e:  # noqa: BLE001
            print(f"[agent_runner] trajectory inject skipped: {_e}")
        if trigger_context:
            # Inject trigger context as a user message so the model knows
            # what fired (e.g. "an inbox item was added: <text>")
            ctx_str = json.dumps(trigger_context, indent=2, default=str)
            messages.append(ChatMessage(
                role="user",
                content=(
                    f"Context (why you were triggered):\n```json\n{ctx_str}\n```\n\n"
                    f"Take whatever action is appropriate."
                ),
            ))

        if critic_note:
            messages.append(ChatMessage(
                role="user",
                content=(
                    f"A reviewer flagged your previous attempt: {critic_note}\n"
                    f"Produce a corrected, complete answer that addresses this."
                ),
            ))

        max_iter = self.DEFAULT_MAX_ITERATIONS
        deadline = time.monotonic() + spec.timeout_seconds

        # Per-agent model routing: an agent spec's `model` field (e.g.
        # "ollama:qwen3:30b-a3b") overrides the service default for this run.
        # Non-ollama backends (anthropic:* etc.) are not routed here yet and
        # fall back to the local default (Phase 2 is local-first).
        agent_model = _resolve_ollama_model(spec.model)

        for iteration in range(max_iter):
            run.iterations = iteration + 1

            now = time.monotonic()
            if now > deadline:
                run.status = RunStatus.TIMEOUT
                run.error = f"timeout after {spec.timeout_seconds}s"
                return

            # Bound THIS chat call (including its own internal retries) by
            # whatever's left of the run's budget. Without this, the deadline
            # is only re-checked between loop iterations — a single slow LLM
            # call can block well past a "60s" timeout, and by the time it
            # finally returns the result gets discarded anyway. Floor the
            # budget so a nearly-exhausted deadline still gives the model a
            # fair last shot instead of cancelling almost instantly.
            chat_budget = max(deadline - now, self.MIN_CHAT_TIMEOUT_SECONDS)

            try:
                response = await asyncio.wait_for(
                    self._chat_with_retry(
                        messages=messages,
                        tools=ollama_tools,
                        agent_model=agent_model,
                    ),
                    timeout=chat_budget,
                )
            except asyncio.TimeoutError:
                run.status = RunStatus.TIMEOUT
                run.error = f"timeout — the AI didn't finish within {spec.timeout_seconds}s"
                return
            except (httpx.HTTPError, httpx.ConnectError, httpx.TimeoutException):
                text = await self._fallback_complete(spec, messages)
                if text:
                    run.result = text
                    run.status = RunStatus.SUCCESS
                    run.error = (
                        "degraded: local model unavailable — used fallback "
                        + (spec.fallback_model or "")
                    )
                    return
                raise

            assistant_msg = response.message
            content = assistant_msg.content
            tool_calls = assistant_msg.tool_calls  # list[ToolCall]

            # If no tool calls, the model is done — record the final result
            if not tool_calls:
                run.result = content
                run.status = RunStatus.SUCCESS
                return

            # Otherwise: append the assistant's message, then execute each
            # tool call, then add the tool results as 'tool' role messages
            messages.append(assistant_msg)
            for tc in tool_calls:
                decision = autonomy.classify(tc.name, tc.arguments)
                if decision.decision != "allow":
                    run.escalations.append({
                        "tool": tc.name, "args": tc.arguments,
                        "decision": decision.decision, "reason": decision.reason,
                    })
                    run.tool_calls.append({
                        "tool": tc.name, "args": tc.arguments,
                        "gate": decision.decision,
                        "result_preview": f"[{decision.decision}] {decision.reason}",
                    })
                    messages.append(ChatMessage(
                        role="tool",
                        content=json.dumps({
                            "gated": True, "decision": decision.decision,
                            "reason": decision.reason,
                            "note": "Action NOT executed — requires human approval.",
                        }),
                        tool_call_id=tc.id,
                    ))
                    continue

                tool = get_tool_by_name(tools, tc.name)
                if tool is None:
                    tool_result = {"error": f"unknown tool: {tc.name}"}
                else:
                    try:
                        tool_result = await tool.handler(**tc.arguments)
                    except Exception as e:
                        tool_result = {"error": f"tool raised: {type(e).__name__}: {e}"}

                try:
                    events.publish({"type": "agent.run", "phase": "step", "agent": spec.name, "run_id": run.id, "tool": tc.name})
                except Exception:
                    pass

                run.tool_calls.append({
                    "tool": tc.name,
                    "args": tc.arguments,
                    "result_preview": str(tool_result)[:200],
                })
                messages.append(ChatMessage(
                    role="tool",
                    content=json.dumps(tool_result, default=str),
                    tool_call_id=tc.id,
                ))

        # Hit iteration cap
        run.status = RunStatus.FAILED
        run.error = f"max iterations ({max_iter}) reached without a final answer"

    async def _verify(
        self,
        spec: AgentSpec,
        run: AgentRun,
        trigger_context: Optional[dict],
    ) -> None:
        """Critic gate: review a SUCCESS output, then act on the verdict.

        pass     → nothing (record as-is).
        retry    → ONE corrective re-run with the critic's note; re-verify once
                   for observability but never loop again.
        escalate → keep the output but flag it (run.critic + notify) for review.

        Fail-open: any critic error is swallowed so the run still completes.
        """
        goal = (spec.description or "").strip()
        if trigger_context:
            goal = (goal + " | trigger: " + json.dumps(trigger_context, default=str))[:600]
        try:
            verdict = await critic.verify(goal, run.result or "", run.agent)
        except Exception as e:  # noqa: BLE001
            print(f"[agent_runner] critic crashed (ignored): {e}")
            return
        run.critic = verdict.to_dict()

        if verdict.verdict == "retry":
            try:
                events.publish({"type": "agent.run", "phase": "retry",
                                "agent": run.agent, "run_id": run.id,
                                "reason": verdict.reason})
            except Exception:
                pass
            await self._execute(spec, run, trigger_context, critic_note=verdict.reason)
            # Re-stamp timing to include the corrective pass.
            run.finished_at = datetime.now().isoformat(timespec="microseconds")
            run.duration_seconds = (
                datetime.fromisoformat(run.finished_at).timestamp()
                - datetime.fromisoformat(run.started_at).timestamp()
            )
            if run.status == RunStatus.SUCCESS and run.result:
                try:
                    run.critic = (await critic.verify(goal, run.result, run.agent)).to_dict()
                except Exception:
                    pass
        elif verdict.verdict == "escalate":
            try:
                notify.notify(f"● review: {run.agent}", verdict.reason[:140])
            except Exception:
                pass

    def cancel(self, run_id: str) -> bool:
        """Cancel an in-flight run. Returns True if cancelled."""
        task = self._in_flight.get(run_id)
        if task and not task.done():
            task.cancel()
            return True
        return False


class AgentRunnerError(Exception):
    """Raised when the runner can't complete a request."""
