"""Academic OS — FastAPI application.

Single-process app that:
- Serves the React webui (built into ../webui/dist) on /
- Exposes /api/* REST endpoints per panel
- Exposes /ws/events WebSocket for live agent events
- Holds the OllamaService and AgentRunner as app.state

Run locally: `uvicorn backend.app:app --port 7878`
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from backend.ollama import OllamaService
from backend.services.agent_loader import AgentLoader
from backend.services.agent_runner import (
    AgentRunner,
    AgentRunnerError,
    RunStore,
)
from backend.services.scheduler import (
    AgentScheduler,
    TriggerDedupe,
    TriggerEngine,
)
from backend.services.browser import BrowserService, BrowserServiceError
from backend.services.calendar import (
    AppleCalendarService,
    CalendarServiceError,
)
from backend.services.inbox import InboxService, InboxServiceError
from pydantic import BaseModel, Field
from datetime import date as _date

from backend.vault import agentic_os_dir, resolve_vault_path
from backend.services import events

# Where the built frontend lives (set by `npm run build` in frontend/)
# Serve the React webui from its OWN build dir (webui/dist) so the SvelteKit
# build (frontend/build, rebuilt by bin/start.sh --build) can never overwrite it.
FRONTEND_BUILD = Path(__file__).parent.parent / "webui" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """App startup/shutdown.

    On startup: warm the Ollama model so the first user interaction isn't
    a 12-second cold load. On shutdown: close the Ollama HTTP client.
    """
    app.state.ollama = OllamaService()

    async def _warm_models() -> None:
        """Warm the primary LLM + embed model into RAM so first use isn't a cold
        load. Runs in the BACKGROUND (non-blocking) so the server is ready
        immediately; with OLLAMA_KEEP_ALIVE the models then stay resident."""
        try:
            secs = await app.state.ollama.warm_model()
            print(f"[startup] warmed {app.state.ollama.model} in {secs:.2f}s")
        except Exception as e:
            print(f"[startup] WARNING: LLM warmup failed: {e!r}")
        try:
            from backend.services.memory_index import embed as _embed
            await _embed("warm")
            print("[startup] warmed embed model")
        except Exception as e:
            print(f"[startup] WARNING: embed warmup failed: {e!r}")

    # Don't block startup on the ~20s cold load — warm in the background.
    asyncio.create_task(_warm_models())
    # Inbox service — points at data/inbox/ inside the data root.
    inbox_data = agentic_os_dir() / "data" / "inbox"
    app.state.inbox = InboxService(data_dir=inbox_data)
    # Agent runner — loads agents/*.md from the data root, runs them on
    # demand via Ollama, persists runs to data/agents/runs.jsonl.
    # Wires the per-service factories so agent tool calls hit real services.
    app.state.agent_loader = AgentLoader(agents_dir=agentic_os_dir() / "agents")
    app.state.run_store = RunStore(
        store_path=agentic_os_dir() / "data" / "agents" / "runs.jsonl"
    )
    # Durability: reconcile any runs orphaned by a crash (stuck "running") so a
    # restart presents an honest state instead of eternal in-flight runs.
    try:
        _recovered = app.state.run_store.recover_interrupted()
        if _recovered:
            print(f"[startup] recovered {len(_recovered)} interrupted run(s): {_recovered}")
    except Exception as _rec_err:
        print(f"[startup] WARNING: run recovery failed: {_rec_err!r}")
    app.state.agent_runner = AgentRunner(
        ollama=app.state.ollama,
        agent_loader=app.state.agent_loader,
        run_store=app.state.run_store,
        calendar_service_factory=_calendar_service,
        inbox_service_factory=lambda: app.state.inbox,
        browser_service_factory=lambda: app.state.browser,
    )
    # Scheduler + trigger engine — turn the runner into an autonomous loop.
    app.state.agent_scheduler = AgentScheduler(
        agent_loader=app.state.agent_loader,
        runner=app.state.agent_runner,
    )
    app.state.agent_scheduler.start()
    app.state.trigger_engine = TriggerEngine(
        agent_loader=app.state.agent_loader,
        runner=app.state.agent_runner,
        dedupe=TriggerDedupe(cooldown_seconds=10),
    )
    # Browser service — talks to camofox-browser on localhost:9377.
    # Lazy: only connects when /api/browser/* is first hit. If the
    # server isn't running, the endpoint returns 503 with a helpful msg.
    app.state.browser = BrowserService()
    # Daily deadline reminder (native macOS notification, one per day).
    from backend.services.deadline_reminders import reminder_loop
    _reminder_task = asyncio.create_task(reminder_loop())
    # Canvas auto-sync (every 6h, only when a token is configured).
    from backend.services.canvas_sync import auto_sync_loop
    _canvas_task = asyncio.create_task(auto_sync_loop())
    yield
    _reminder_task.cancel()
    _canvas_task.cancel()
    await app.state.ollama.close()
    app.state.agent_scheduler.stop()


# Active WebSocket connections — the watcher fans out events to all of them.
_active_ws_connections: set = set()


def _send_to_ws(ws, msg):
    """Helper: send a JSON message to a WebSocket. Removes it from the set on failure."""
    import asyncio
    try:
        # We're in the event loop now. The send is awaited by the loop.
        asyncio.create_task(ws.send_json(msg))
    except Exception:
        _active_ws_connections.discard(ws)


app = FastAPI(title="Academic OS", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",  # Vite dev server
        "http://localhost:7878",  # production same-origin
        "http://127.0.0.1:7878",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# === Academic OS module routers ===================================
from backend.routers.applications import router as applications_router  # noqa: E402
from backend.routers.courses import router as courses_router  # noqa: E402
from backend.routers.study import router as study_router  # noqa: E402
from backend.routers.documents import router as documents_router  # noqa: E402
from backend.routers.routines import router as routines_router  # noqa: E402
from backend.routers.profile import router as profile_router  # noqa: E402
from backend.routers.connectors import router as connectors_router  # noqa: E402
from backend.routers.localai import router as localai_router  # noqa: E402

app.include_router(profile_router)
app.include_router(connectors_router)
app.include_router(localai_router)
app.include_router(applications_router)
app.include_router(courses_router)
app.include_router(study_router)
app.include_router(documents_router)
app.include_router(routines_router)


@app.get("/health")
def health() -> dict[str, Any]:
    """Liveness check. Returns ok always; /health/ready checks dependencies."""
    return {"status": "ok"}


@app.get("/api/meta")
def app_meta() -> dict:
    """App version + update repo, for the Settings about/update check."""
    from backend.version import APP_VERSION, UPDATE_REPO
    return {"version": APP_VERSION, "repo": UPDATE_REPO}


@app.get("/api/health/ready")
async def health_ready() -> JSONResponse:
    """Readiness check — verifies Ollama is reachable."""
    ollama_ok = await app.state.ollama.health()
    body = {"status": "ready" if ollama_ok else "degraded", "ollama": ollama_ok}
    code = 200 if ollama_ok else 503
    return JSONResponse(body, status_code=code)


# === LLM Hub (Panel L) — unified multi-LLM switchboard ============
from backend.llm_hub import (
    get_backend, status_all,
    ChatMessage, ChatResult,
    list_threads, get_thread, save_thread,
)  # noqa: E402


@app.get("/api/llms/status")
async def llms_status() -> dict:
    """Probe every backend; return online status + account + models."""
    results = await status_all()
    return {
        name: {
            "online": r.online,
            "message": r.message,
            "account": r.account,
            "latency_ms": r.latency_ms,
            "models": [{"id": m.id, "label": m.label, "context": m.context}
                       for m in r.models],
        }
        for name, r in results.items()
    }


@app.get("/api/llms/models")
async def llms_models(backend: str):
    """List models for a specific backend."""
    try:
        b = get_backend(backend)
    except KeyError as e:
        return JSONResponse({"error": str(e)}, status_code=404)
    models = await b.models()
    return {
        "backend": backend,
        "models": [{"id": m.id, "label": m.label, "context": m.context}
                   for m in models],
    }


@app.post("/api/llms/chat")
async def llms_chat(body: dict) -> JSONResponse:
    """Route a chat call to the chosen backend.

    Body: {"backend": "...", "model": "...", "messages": [{"role", "content"}, ...],
           "thread_id": optional existing thread id}
    Returns: {"backend", "model", "content", "tokens", "elapsed_ms", "thread_id"}
    """
    backend_name = body.get("backend", "")
    model = body.get("model", "")
    raw_msgs = body.get("messages", [])
    thread_id = body.get("thread_id") or None
    if not backend_name:
        return JSONResponse({"error": "backend is required"}, status_code=400)
    if not raw_msgs:
        return JSONResponse({"error": "messages is required"}, status_code=400)
    try:
        b = get_backend(backend_name)
    except KeyError as e:
        return JSONResponse({"error": str(e)}, status_code=404)
    # Find the most recent user message for thread-title seeding.
    last_user = next(
        (m for m in reversed(raw_msgs) if m.get("role") == "user"),
        None,
    )
    user_text = last_user["content"] if last_user else ""
    msgs = [ChatMessage(role=m["role"], content=m["content"]) for m in raw_msgs]
    # Phase 1.4: inject relevant memory as a system message (local-first, best-effort).
    # Affects only what the model sees this turn; does NOT change what save_thread persists.
    if user_text and os.environ.get("MEMORY_RECALL", "1") != "0":
        try:
            from backend.services.memory_recall import recall as _recall
            _ctx = _recall(user_text)
            if _ctx:
                msgs.insert(0, ChatMessage(role="system", content=_ctx))
        except Exception as _recall_err:
            print(f"[memory] recall failed: {_recall_err}")
    try:
        result: ChatResult = await b.chat(msgs, model=model)
    except Exception as e:
        return JSONResponse(
            {"error": f"{type(e).__name__}: {e}"},
            status_code=502,
        )
    # Persist the turn if we have user text (thread stays useful for replay).
    new_thread_id = thread_id
    if user_text and result.content:
        try:
            new_thread_id = save_thread(
                thread_id, backend_name, model or result.model,
                user_text, result.content,
                assistant_meta={
                    "tokens": result.tokens,
                    "elapsed_ms": result.elapsed_ms,
                },
            )
        except Exception as persist_err:
            # Persistence is best-effort; don't fail the chat on disk error.
            print(f"[llm_hub] persist failed: {persist_err}")
    # Phase 1.1: fire-and-forget memory consolidation (local-first, best-effort).
    # Never blocks or fails the chat response.
    if new_thread_id and os.environ.get("MEMORY_CONSOLIDATION", "1") != "0":
        asyncio.create_task(_consolidate_safe(new_thread_id))
    return JSONResponse({
        "backend": result.backend,
        "model": result.model,
        "content": result.content,
        "tokens": result.tokens,
        "elapsed_ms": result.elapsed_ms,
        "thread_id": new_thread_id,
    })


@app.post("/api/llms/chat/stream")
async def llms_chat_stream(body: dict):
    """Stream chat tokens via SSE from Ollama or Nous backends.

    Body: {"backend": "ollama|nous", "model": "...", "messages": [...], "thread_id": optional}
    Emits: data: {"token": <piece>}  per content chunk
           data: {"done": true, "thread_id": <tid>, "content": <full>, "tokens": N}  at end
    Supported backends: "ollama", "nous"
    """
    backend_name = body.get("backend", "")
    model = body.get("model", "")
    raw_msgs = body.get("messages", [])
    thread_id = body.get("thread_id") or None

    if backend_name not in ("ollama", "nous"):
        return JSONResponse(
            {"error": "streaming supported for ollama and nous only"},
            status_code=400,
        )

    last_user = next(
        (m for m in reversed(raw_msgs) if m.get("role") == "user"),
        None,
    )
    user_text = last_user["content"] if last_user else ""

    async def gen():
        full = ""
        total_tokens = 0
        try:
            if backend_name == "ollama":
                from backend.ollama import ChatMessage as OllamaChatMessage
                oll_msgs = [OllamaChatMessage(role=m["role"], content=m["content"]) for m in raw_msgs]
                async for chunk in app.state.ollama.stream_chat(messages=oll_msgs):
                    # Ollama NDJSON: {"message": {"role": "assistant", "content": "<piece>"}, ...}
                    piece = chunk.get("message", {}).get("content", "")
                    if piece:
                        full += piece
                        yield f"data: {json.dumps({'token': piece})}\\n\\n"
            elif backend_name == "nous":
                from backend.llm_hub import ChatMessage as LLMChatMessage, get_backend
                nous_backend = get_backend("nous")
                llm_msgs = [LLMChatMessage(role=m["role"], content=m["content"]) for m in raw_msgs]
                async for chunk in nous_backend.chat_stream(messages=llm_msgs, model=model):
                    if "error" in chunk:
                        yield f"data: {json.dumps(chunk)}\\n\\n"
                        break
                    if "token" in chunk:
                        piece = chunk["token"]
                        full += piece
                        yield f"data: {json.dumps({'token': piece})}\\n\\n"
                    if "done" in chunk and chunk["done"]:
                        total_tokens = chunk.get("tokens", 0)
                        break
            # Persist the completed turn (best-effort).
            tid = thread_id
            try:
                tid = save_thread(thread_id, backend_name, model or "", user_text, full)
            except Exception as persist_err:
                print(f"[llm_hub] stream persist failed: {persist_err}")
            yield f"data: {json.dumps({'done': True, 'thread_id': tid, 'content': full, 'tokens': total_tokens})}\\n\\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\\n\\n"

    return StreamingResponse(gen(), media_type="text/event-stream")


@app.get("/api/llms/history")
async def llms_history() -> dict:
    """List recent chat threads (most recent first)."""
    return {"threads": list_threads()}


@app.get("/api/llms/history/{tid}")
async def llms_history_thread(tid: str):
    """Fetch one thread by id."""
    try:
        thread = get_thread(tid)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    if thread is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    return thread


async def _consolidate_safe(tid: str) -> None:
    """Run memory consolidation for a thread; swallow all errors (best-effort)."""
    try:
        from backend.services.memory import consolidate_thread_id
        res = await consolidate_thread_id(tid)
        if res.error:
            print(f"[memory] consolidate {tid}: {res.error}")
    except Exception as e:
        print(f"[memory] consolidate {tid} crashed: {type(e).__name__}: {e}")


@app.post("/api/memory/consolidate/{tid}")
async def memory_consolidate(tid: str) -> JSONResponse:
    """Manually trigger memory consolidation for a saved thread."""
    from backend.services.memory import consolidate_thread_id
    result = await consolidate_thread_id(tid)
    return JSONResponse(result.to_dict())


@app.post("/api/consensus")
async def consensus_endpoint(body: dict) -> JSONResponse:
    """Multi-model second opinion. Body: {"question": str, "panel": [str]?,
    "mode": "synthesize"|"council"?}. Asks a panel of different model families;
    "council" adds a cross-review round and picks the best response."""
    question = (body or {}).get("question", "").strip()
    if not question:
        return JSONResponse({"error": "question is required"}, status_code=400)
    panel = (body or {}).get("panel") or None
    mode = (body or {}).get("mode") or "synthesize"
    from backend.services.consensus import consensus
    return JSONResponse(await consensus(question, panel=panel, mode=mode))


@app.post("/api/moa")
async def moa_endpoint(body: dict) -> JSONResponse:
    """Mixture of Agents ("Ministry of Experts") — advisors analyze in parallel,
    an aggregator writes the single answer.

    Body: {"question": str, "advisors": [str]?, "aggregator": str?,
           "include_advice": bool?}. Advisors default to codex+gemini (topped up
           from droid/cursor/ollama); aggregator defaults to claude. Advisor
           guidance is private unless include_advice=true.

    Unlike /api/consensus (peer voting), MoA folds advisor guidance into the
    aggregator's prompt so one model produces the final answer.

    Not persisted to thread history by design — MoA is a one-shot second-brain
    query, not a conversation. Use /api/llms/chat for threaded chat.
    """
    b = body or {}
    question = b.get("question", "").strip()
    if not question:
        return JSONResponse({"error": "question is required"}, status_code=400)
    advisors = b.get("advisors") or None
    aggregator = b.get("aggregator") or "claude"
    include_advice = bool(b.get("include_advice", False))
    from backend.services.moa import moa
    return JSONResponse(await moa(
        question, advisors=advisors, aggregator=aggregator,
        include_advice=include_advice,
    ))


@app.post("/api/moa/stream")
async def moa_stream_endpoint(body: dict):
    """Streaming MoA — SSE progress events so the UI can show the advisor panel
    filling in before the final answer lands.

    Body: same as /api/moa. Emits `data: {json}\\n\\n` per phase event
    (advisors → advisor_done* → aggregating → done | error). The aggregator's
    answer arrives in the terminal `done` event (advisor calls are one-shot, so
    no token streaming yet — that's a follow-up gated on an OpenRouterBackend).
    """
    b = body or {}
    question = b.get("question", "").strip()
    if not question:
        return JSONResponse({"error": "question is required"}, status_code=400)
    advisors = b.get("advisors") or None
    aggregator = b.get("aggregator") or "claude"
    include_advice = bool(b.get("include_advice", False))
    from backend.services.moa import moa_stream

    async def gen():
        try:
            async for event in moa_stream(
                question, advisors=advisors, aggregator=aggregator,
                include_advice=include_advice,
            ):
                yield f"data: {json.dumps(event)}\n\n"
        except Exception as e:  # noqa: BLE001 — never leak a raw 500 into the stream
            yield f"data: {json.dumps({'phase': 'error', 'error': str(e)})}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")


@app.post("/api/memory/compact")
async def memory_compact_now() -> JSONResponse:
    """Manually run the memory distillation pass (merge/supersede/evict/age-out).
    Reversible — removed items are archived under memory/_archive/."""
    from backend.services.memory_compact import compact_all
    return JSONResponse(await compact_all())


@app.get("/api/memory/search")
async def memory_search(q: str = "", k: int = 8) -> dict:
    """Search the memory index. Returns matching memory items."""
    from backend.services.memory_index import search
    items = search(q, k)
    return {
        "query": q,
        "results": [
            {
                "kind": it.kind,
                "subject": it.subject,
                "body": it.body,
                "tags": it.tags,
                "ts": it.ts,
                "item_id": it.item_id,
                "vault_path": it.vault_path,
            }
            for it in items
        ],
    }


@app.get("/api/memory/context")
async def memory_context(q: str = "", k: int = 6) -> dict:
    """Preview the memory context block that would be injected for a query."""
    from backend.services.memory_recall import recall
    return {"query": q, "context": recall(q, k)}


@app.get("/api/memory/items")
def memory_items() -> dict:
    """Everything the app remembers, newest first (Settings privacy view)."""
    from backend.services import memory_index
    try:
        memory_index.init_db()
        items = memory_index.all_items()
    except Exception as e:  # read-only view — never 500
        return {"items": [], "count": 0, "error": str(e)}
    items.sort(key=lambda i: i.ts or "", reverse=True)
    return {
        "items": [
            {"item_id": i.item_id, "kind": i.kind, "subject": i.subject,
             "body": i.body, "ts": i.ts}
            for i in items
        ],
        "count": len(items),
    }


@app.delete("/api/memory/items/{item_id}")
def memory_item_delete(item_id: str) -> JSONResponse:
    """Forget one memory — removed from the index, recall stops immediately."""
    from backend.services import memory_index
    if memory_index.delete_item(item_id):
        return JSONResponse({"ok": True, "item_id": item_id})
    return JSONResponse({"error": "not_found", "item_id": item_id}, status_code=404)


@app.post("/api/memory/forget_all")
def memory_forget_all() -> dict:
    """Forget everything: wipe the index AND the memory markdown notes."""
    import shutil
    from backend.services import memory_index
    from backend.vault import resolve_vault_path
    n = memory_index.delete_all()
    notes_dir = resolve_vault_path() / "notes" / "memory"
    if notes_dir.exists():
        shutil.rmtree(notes_dir, ignore_errors=True)
    return {"ok": True, "forgotten": n}


@app.get("/api/memory/stats")
def memory_stats() -> dict:
    """Memory-spine stats for the Memory panel: distribution by kind and a
    30-day cumulative growth curve, computed from the memory index. Read-only."""
    from collections import Counter
    from datetime import datetime as _dt, timedelta as _td, timezone as _tz
    from backend.services import memory_index
    try:
        memory_index.init_db()
        items = memory_index.all_items()
    except Exception as e:  # never 500 a read-only panel
        return {"total": 0, "by_kind": {}, "growth": [], "error": str(e)}
    by_kind = dict(Counter(i.kind for i in items))
    today = _dt.now(_tz.utc).date()

    def _day(ts: str):
        try:
            return _dt.fromisoformat((ts or "").replace("Z", "+00:00")).date()
        except Exception:
            return today

    days = [today - _td(days=(29 - k)) for k in range(30)]
    growth = [sum(1 for i in items if _day(i.ts) <= d) for d in days]
    return {"total": len(items), "by_kind": by_kind, "growth": growth}


# === Observability (roadmap Phase B) — trajectory traces + eval runs ===

@app.get("/api/traces")
async def traces_recent(n: int = 50) -> dict:
    """Recent agent-run trajectories (roadmap B1). Newest first."""
    from backend.services.trace import TraceStore
    try:
        records = TraceStore().recent(n)
    except Exception as e:  # never 500 a read-only panel
        return {"count": 0, "records": [], "error": str(e)}
    return {"count": len(records), "records": list(reversed(records))}


@app.get("/api/evals")
async def evals_latest() -> dict:
    """Latest eval run summary + recent run stamps (roadmap B2)."""
    from backend.services.evals import EvalStore
    try:
        store = EvalStore()
        latest = store.baseline()  # newest run on disk
        runs = sorted(p.stem for p in store.base_dir.glob("*.json"))[-20:]
    except Exception as e:
        return {"latest": None, "runs": [], "error": str(e)}
    return {"latest": latest, "runs": list(reversed(runs))}


# === Approvals (Panel P) — human approval inbox for gated escalations ===

@app.get("/api/approvals")
async def approvals_list() -> dict:
    """List pending gated escalations awaiting human decision.

    Returns {pending: list[dict]} where each item has:
    id, run_id, idx, agent, tool, args, reason, ts, status.
    Items already approved or dismissed are excluded.
    """
    from backend.services.approvals import list_pending
    return {"pending": list_pending(app.state.run_store)}


@app.post("/api/approvals/decide")
async def approvals_decide(body: dict) -> JSONResponse:
    """Record a human decision (approved | dismissed) for a pending item.

    Body: {"item_id": "<run_id>:<idx>", "decision": "approved"|"dismissed"}
    Returns {"decision": record, "exec_result": ...} on success; 400 on invalid input.
    If decision is "approved", attempts to execute the approved tool via execute_item.
    exec_result will report {"executed": False, "reason": "..."}  when the tool is not
    in the runner's registry (common — outward tools are not registered by default).
    """
    from backend.services.approvals import (
        list_pending, decide, execute_item, was_executed, mark_executed,
    )
    item_id = (body or {}).get("item_id", "")
    decision = (body or {}).get("decision", "")
    if not item_id or decision not in ("approved", "dismissed"):
        return JSONResponse(
            {"error": "item_id and decision (approved|dismissed) required"},
            status_code=400,
        )
    # Capture pending BEFORE recording — once decide() appends the decision record
    # the item will be filtered out of list_pending on the next call.
    pending = list_pending(app.state.run_store)
    item = next((p for p in pending if p["id"] == item_id), None)

    record = decide(item_id, decision)

    exec_result = None
    if decision == "approved":
        if item is None:
            exec_result = {"executed": False, "reason": "item not found"}
        elif was_executed(item_id):
            # Durability: this action already fired on a prior call — never repeat
            # an irreversible side-effect on replay/retry.
            exec_result = {"executed": False, "reason": "already executed (idempotent)"}
        else:
            try:
                tools = app.state.agent_runner._build_tools()
                exec_result = await execute_item(item, tools)
                if isinstance(exec_result, dict) and exec_result.get("executed"):
                    mark_executed(item_id, str(exec_result.get("result", ""))[:200])
                # If an approved action changed an agent's schedule, re-register
                # cron jobs immediately rather than waiting on the (iCloud-laggy)
                # file watcher — so the change takes effect the moment it's approved.
                if (
                    isinstance(exec_result, dict)
                    and exec_result.get("executed")
                    and item.get("tool") == "loop.set_schedule"
                ):
                    try:
                        app.state.agent_scheduler.rescan()
                    except Exception as re:
                        print(f"[approvals] rescan after set_schedule failed: {re}")
            except Exception as e:
                exec_result = {"executed": False, "reason": f"{type(e).__name__}: {e}"}

    return JSONResponse({"decision": record, "exec_result": exec_result})


@app.get("/api/activity/recent")
async def activity_recent(limit: int = 20) -> dict:
    """Merged, newest-first list of recent OS activity for the Command Center:
    agent runs + generated artifacts (CoS syntheses, code builds, daily briefs)."""
    from datetime import datetime as _dt
    items: list[dict] = []

    # 1) Agent runs — dedupe to the final record per id
    try:
        by_id: dict[str, dict] = {}
        for r in app.state.run_store.list(limit=60):
            rid = r.get("id")
            if rid:
                by_id[rid] = r  # later (final) record wins
        for r in by_id.values():
            sa = r.get("started_at", "")
            try:
                epoch = _dt.fromisoformat(sa).timestamp()
            except Exception:
                epoch = 0.0
            items.append({
                "kind": "run",
                "label": str(r.get("agent", "")).upper(),
                "sub": str(r.get("status", "")),
                "epoch": epoch,
                "ref": str(r.get("id", "")),
            })
    except Exception:
        pass

    # 2) Generated artifacts under output/
    try:
        out = resolve_vault_path() / "output"
        groups = [("cos", "kind"), ("code", "kind"), ("daily", "kind")]
        for sub, _ in groups:
            d = out / sub
            if not d.is_dir():
                continue
            for f in sorted(d.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)[:8]:
                if f.name.startswith("_"):
                    continue
                epoch = f.stat().st_mtime
                preview = None
                if sub == "code":
                    label, kind = f"BUILT {f.stem}", "code"
                    # If the built project has an HTML entry point, offer a preview.
                    proj = Path.home() / "Code" / "agentic-os-projects" / f.stem
                    if (proj / "index.html").is_file() or any(proj.glob("*.html")):
                        preview = f"/preview/{f.stem}/"
                elif sub == "cos":
                    label, kind = "CHIEF OF STAFF", "cos"
                else:
                    label, kind = f"DAILY BRIEF · {f.stem}", "brief"
                items.append({
                    "kind": kind, "label": label,
                    "sub": f"output/{sub}/{f.name}", "epoch": epoch,
                    "ref": f"output/{sub}/{f.name}", "preview": preview,
                })
    except Exception:
        pass

    items.sort(key=lambda x: x.get("epoch") or 0.0, reverse=True)
    out_items = []
    for it in items[:limit]:
        ep = it.pop("epoch", 0.0)
        try:
            it["time"] = _dt.fromtimestamp(ep).strftime("%H:%M") if ep else ""
        except Exception:
            it["time"] = ""
        out_items.append(it)
    return {"items": out_items}


@app.get("/api/activity/detail")
async def activity_detail(kind: str = "", ref: str = "") -> JSONResponse:
    """Return what a recent-activity item actually did — a run's result, or the
    markdown of a generated artifact (CoS synthesis / code summary / brief)."""
    if kind == "run":
        rec = app.state.run_store.get(ref) if ref else None
        if not rec:
            return JSONResponse({"error": "run not found"}, status_code=404)
        return JSONResponse({
            "kind": "run",
            "title": f"{str(rec.get('agent','')).upper()} run",
            "body": rec.get("result") or rec.get("error") or "(no output)",
            "status": rec.get("status"),
            "tool_calls": [t.get("tool") for t in rec.get("tool_calls", [])],
            "escalations": rec.get("escalations", []),
        })
    # Otherwise: an output file under the vault (ref is a relpath).
    if not ref or ".." in ref or not ref.startswith("output/"):
        return JSONResponse({"error": "bad ref"}, status_code=400)
    from backend.services.tools import vault_read
    d = await vault_read(ref)
    if d.get("error"):
        return JSONResponse({"error": d["error"]}, status_code=404)
    return JSONResponse({
        "kind": kind or "file",
        "title": ref.split("/")[-1],
        "body": d.get("content", ""),
        "path": ref,
    })


# === Status (Panel S) — aggregate toolchain health ===
@app.get("/api/status")
async def status_overview() -> JSONResponse:
    """Single-pane-of-glass status across Ollama, Claude Code, Antigravity,
    Hermes, uvicorn (self), and the LaunchAgent. Powers the /s dashboard panel."""
    import os
    import shutil
    import subprocess
    from pathlib import Path

    def cmd(*args: str, timeout: float = 1.5) -> tuple[int, str, str]:
        try:
            r = subprocess.run(
                list(args),
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
            return r.returncode, r.stdout.strip(), r.stderr.strip()
        except (FileNotFoundError, subprocess.TimeoutExpired, Exception) as e:
            return 1, "", str(e)

    # --- Ollama ---
    ollama_ok = False
    ollama_models: list[str] = []
    try:
        ollama_ok = await app.state.ollama.health()
        if ollama_ok:
            tags_rc, tags_out, _ = cmd("curl", "-s", "-m", "2",
                                       "http://127.0.0.1:11434/api/tags")
            if tags_rc == 0 and tags_out:
                import json as _json
                try:
                    ollama_models = [m["name"] for m in _json.loads(tags_out).get("models", [])]
                except Exception:
                    pass
    except Exception:
        pass

    # --- Claude Code ---
    claude_path = shutil.which("claude") or str(Path.home() / ".npm-global/bin/claude")
    claude_installed = Path(claude_path).exists()
    claude_version: str | None = None
    claude_auth_ok: bool | None = None
    if claude_installed:
        rc, out, _ = cmd(claude_path, "--version")
        if rc == 0 and out:
            claude_version = out.split()[0] if out else None
        # Auth probe — `claude auth status` is the reliable cross-platform
        # check. On macOS the OAuth token lives in Keychain (no
        # ~/.claude/.credentials.json on disk), and the same is true on
        # Linux via the secret service. Exit 0 means a valid credential
        # was found, regardless of where it's stored.
        rc, out, _ = cmd(claude_path, "auth", "status")
        claude_auth_ok = (rc == 0)

    # --- Antigravity IDE ---
    ag_app = Path("/Applications/Antigravity IDE.app")
    ag_running = False
    if ag_app.exists():
        rc, out, _ = cmd("pgrep", "-fl", "Antigravity IDE.app/Contents/MacOS/Electron")
        ag_running = rc == 0 and "Antigravity" in (out or "")

    # --- Hermes ---
    hermes_running = False
    hermes_version: str | None = None
    hermes_path = shutil.which("hermes")
    rc, out, _ = cmd("pgrep", "-fl", "Hermes.app")
    hermes_running = rc == 0 and "Hermes.app" in (out or "")
    if hermes_path:
        rc, out, _ = cmd(hermes_path, "--version")
        if rc == 0 and out:
            hermes_version = out.split("\n")[0][:64]

    # --- Uvicorn (self) ---
    self_pid = os.getpid()
    rc, out, _ = cmd("ps", "-o", "etime=", "-p", str(self_pid))
    self_uptime = out.strip() or None

    body = {
        "ollama": {
            "ok": ollama_ok,
            "url": "http://127.0.0.1:11434",
            "models": ollama_models,
            "default": os.environ.get("OLLAMA_DEFAULT_MODEL", "gemma4:latest"),
        },
        "claude_code": {
            "installed": claude_installed,
            "path": claude_path,
            "version": claude_version,
            "authenticated": claude_auth_ok,
        },
        "antigravity": {
            "installed": ag_app.exists(),
            "running": ag_running,
            "path": str(ag_app),
        },
        "hermes": {
            "running": hermes_running,
            "path": hermes_path,
            "version": hermes_version,
        },
        "uvicorn": {
            "pid": self_pid,
            "uptime": self_uptime,
            "host": os.environ.get("BIND_HOST", "127.0.0.1"),
            "port": int(os.environ.get("BIND_PORT", "7878")),
        },
        "ts": __import__("datetime").datetime.utcnow().isoformat() + "Z",
    }
    return JSONResponse(body)


def _calendar_service() -> AppleCalendarService:
    """Lazy-create the calendar service so startup doesn't fail if .env is missing."""
    if not hasattr(app.state, "calendar") or app.state.calendar is None:
        app.state.calendar = AppleCalendarService()
    return app.state.calendar


@app.get("/api/calendar/calendars")
def calendar_calendars() -> dict:
    """List all iCloud calendars the user has access to."""
    try:
        svc = _calendar_service()
        cals = svc.list_calendars()
        return {"calendars": [c.to_dict() for c in cals], "count": len(cals)}
    except CalendarServiceError as e:
        return JSONResponse(
            {"error": "calendar_unavailable", "detail": str(e)},
            status_code=503,
        )


@app.get("/api/calendar/events")
def calendar_events(
    start: str = Query(..., description="ISO-8601 datetime, inclusive"),
    end: str = Query(..., description="ISO-8601 datetime, exclusive"),
    calendar: str | None = Query(None, description="Filter by calendar name"),
) -> dict:
    """List events in [start, end) from all (or one) calendar."""
    from datetime import datetime
    try:
        s = datetime.fromisoformat(start)
        e = datetime.fromisoformat(end)
    except ValueError as ve:
        return JSONResponse(
            {"error": "bad_date", "detail": str(ve)},
            status_code=400,
        )
    try:
        svc = _calendar_service()
        events = svc.list_events(start=s, end=e, calendar_name=calendar)
        return {
            "events": [ev.to_dict() for ev in events],
            "count": len(events),
            "start": s.isoformat(),
            "end": e.isoformat(),
        }
    except CalendarServiceError as ce:
        return JSONResponse(
            {"error": "calendar_unavailable", "detail": str(ce)},
            status_code=503,
        )


@app.get("/api/browser/health")
async def browser_health() -> JSONResponse:
    """camofox-browser engine status. Returns 503 if not running.

    Catches connection errors too — on machines without camofox (any student
    laptop) the health probe must degrade, not traceback.
    """
    import httpx as _httpx
    try:
        return JSONResponse(await app.state.browser.health(), status_code=200)
    except (BrowserServiceError, _httpx.ConnectError, _httpx.ConnectTimeout, OSError) as e:
        return JSONResponse(
            {"error": "browser_unavailable", "detail": str(e)},
            status_code=503,
        )


@app.get("/api/browser/research/fetch")
async def browser_research_fetch(url: str = Query(..., description="URL to fetch")):
    """Open a tab, navigate to the URL, snapshot + extract links, close tab.

    Returns {url, final_url, text, links, truncated, total_chars, backend}.
    Read-only — never submits forms, never follows logins.
    """
    import httpx
    try:
        result = await app.state.browser.research_fetch(url=url)
        return {**result, "backend": "camofox"}
    except (httpx.ConnectError, httpx.ConnectTimeout, BrowserServiceError) as browser_err:
        return JSONResponse(
            {"error": "browser_error", "detail": str(browser_err)},
            status_code=502,
        )


@app.get("/api/browser/research/search")
async def browser_research_search(
    q: str = Query(..., description="Search query"),
    macro: str = Query("@google_search", description="Search macro to use"),
):
    """Run a search via macro (default @google_search), return SERP content + links.

    Returns {query, macro, final_url, text, links, truncated, total_chars, backend}.
    """
    import httpx
    try:
        result = await app.state.browser.research_search(query=q, macro=macro)
        return {**result, "backend": "camofox"}
    except (httpx.ConnectError, httpx.ConnectTimeout, BrowserServiceError) as browser_err:
        return JSONResponse(
            {"error": "browser_error", "detail": str(browser_err)},
            status_code=502,
        )


# === Inbox (Panel E) endpoints ===

class _InboxAddBody(BaseModel):
    text: str = Field(..., min_length=1, description="Required. The thing to remember.")
    priority: str = Field("normal", description="low | normal | high")
    due: _date | None = Field(None, description="Optional due date (ISO YYYY-MM-DD)")
    notes: str = Field("", description="Optional free-form notes")


class _InboxUpdateBody(BaseModel):
    text: str | None = None
    priority: str | None = None
    due: _date | None = None
    notes: str | None = None


@app.get("/api/inbox/items")
def inbox_items(status: str | None = Query(None, description="open | done | snoozed")) -> dict:
    """List inbox items, optionally filtered by status. Newest first."""
    try:
        items = app.state.inbox.list_all(status=status)
        return {"items": [i.to_dict() for i in items], "count": len(items)}
    except InboxServiceError as e:
        return JSONResponse(
            {"error": "bad_input", "detail": str(e)},
            status_code=400,
        )


@app.get("/api/inbox/summary")
def inbox_summary() -> dict:
    """Inbox health: counts by status, by priority, overdue, due today."""
    return app.state.inbox.summary()


@app.post("/api/inbox/items")
def inbox_add_item(body: _InboxAddBody) -> dict:
    """Add a new item to the inbox."""
    try:
        item = app.state.inbox.add(
            text=body.text,
            priority=body.priority,
            due=body.due,
            notes=body.notes,
        )
        return {"ok": True, "item": item.to_dict()}
    except InboxServiceError as e:
        return JSONResponse(
            {"error": "validation", "detail": str(e)},
            status_code=422,
        )


@app.patch("/api/inbox/items/{item_id}")
def inbox_update_item(item_id: str, body: _InboxUpdateBody) -> dict:
    """Update an inbox item (any subset of fields)."""
    try:
        item = app.state.inbox.update(
            item_id,
            text=body.text,
            priority=body.priority,
            due=body.due,
            notes=body.notes,
        )
        return {"ok": True, "item": item.to_dict()}
    except InboxServiceError as e:
        code = 404 if "not found" in str(e) else 422
        return JSONResponse({"error": "inbox_error", "detail": str(e)}, status_code=code)


@app.post("/api/inbox/items/{item_id}/done")
def inbox_mark_done(item_id: str) -> dict:
    try:
        item = app.state.inbox.mark_done(item_id)
        return {"ok": True, "item": item.to_dict()}
    except InboxServiceError as e:
        return JSONResponse({"error": "inbox_error", "detail": str(e)}, status_code=404)


@app.post("/api/inbox/items/{item_id}/reopen")
def inbox_reopen(item_id: str) -> dict:
    try:
        item = app.state.inbox.reopen(item_id)
        return {"ok": True, "item": item.to_dict()}
    except InboxServiceError as e:
        return JSONResponse({"error": "inbox_error", "detail": str(e)}, status_code=404)


@app.delete("/api/inbox/items/{item_id}")
def inbox_delete_item(item_id: str) -> dict:
    try:
        app.state.inbox.delete(item_id)
        return {"ok": True}
    except InboxServiceError as e:
        return JSONResponse({"error": "inbox_error", "detail": str(e)}, status_code=404)


# === Agent runner (Panel A + Phase 3) endpoints ===


class _AgentRunBody(BaseModel):
    """Optional body for POST /api/agents/{name}/run."""
    trigger_context: dict | None = Field(
        None, description="Optional context describing what triggered this run"
    )


@app.get("/api/agents")
def agents_list() -> dict:
    """List all available agent definitions."""
    specs = app.state.agent_loader.list_all()
    return {
        "agents": [
            {
                "name": s.name,
                "description": s.description,
                "model": s.model,
                "fallback_model": s.fallback_model,
                "schedule": s.schedule,
                "trigger": s.trigger,
                "trigger_path": s.trigger_path,
                "enabled": s.enabled,
                "timeout_seconds": s.timeout_seconds,
            }
            for s in specs
        ],
        "count": len(specs),
    }


# NOTE: FastAPI matches routes in declaration order. /api/agents/runs and
# /api/agents/runs/{id} MUST come before /api/agents/{name}, otherwise
# the dynamic path eats the static ones and they 404.


@app.get("/api/agents/runs")
def agents_runs(agent: str | None = Query(None), limit: int = Query(50)) -> dict:
    """List recent agent runs, optionally filtered by agent name."""
    runs = app.state.run_store.list(agent=agent, limit=limit)
    return {"runs": runs, "count": len(runs)}


@app.get("/api/agents/runs/{run_id}")
def agents_run_get(run_id: str) -> dict:
    """Get a single agent run by id."""
    run = app.state.run_store.get(run_id)
    if run is None:
        return JSONResponse({"error": "not_found", "id": run_id}, status_code=404)
    return run


@app.post("/api/agents/runs/{run_id}/cancel")
def agents_run_cancel(run_id: str) -> dict:
    """Cancel an in-flight agent run."""
    cancelled = app.state.agent_runner.cancel(run_id)
    return {"ok": cancelled}


@app.get("/api/agents/{name}")
def agents_get(name: str) -> dict:
    """Get a single agent's full spec (including the full prompt body)."""
    spec = app.state.agent_loader.get(name)
    if spec is None:
        return JSONResponse({"error": "not_found", "name": name}, status_code=404)
    d = spec.to_dict()
    # Also expose the full prompt so the UI can render / edit it
    d["prompt"] = spec.prompt
    return d


@app.post("/api/agents/{name}/run")
async def agent_run(name: str, body: _AgentRunBody | None = None) -> JSONResponse:
    """Run an agent. Returns the AgentRun record.

    Runs in the background — the response comes back as soon as the run
    starts (status "running"); poll /api/agents/runs/{id} to see completion.
    """
    try:
        run = await app.state.agent_runner.run(
            name,
            trigger="manual",
            trigger_context=body.trigger_context if body else None,
            background=True,
        )
        return JSONResponse(run.to_dict(), status_code=202)
    except AgentRunnerError as e:
        return JSONResponse(
            {"error": "agent_error", "detail": str(e)},
            status_code=404 if "not found" in str(e) else 422,
        )


@app.post("/api/scheduler/rescan")
def scheduler_rescan() -> dict:
    """Re-read agent specs and update cron jobs.

    Use after editing an agent's schedule, or after creating a new agent.
    """
    app.state.agent_scheduler.rescan()
    return {
        "ok": True,
        "job_count": app.state.agent_scheduler.job_count(),
        "job_names": app.state.agent_scheduler.job_names(),
    }


@app.get("/api/scheduler/status")
def scheduler_status() -> dict:
    """Current scheduler state."""
    return {
        "running": app.state.agent_scheduler._started,
        "job_count": app.state.agent_scheduler.job_count(),
        "job_names": app.state.agent_scheduler.job_names(),
    }


@app.websocket("/ws/events")
async def websocket_events(ws: WebSocket):
    """Live event stream for the dashboard.

    Server pushes JSON messages of the form:
      {"type": "hello", "ts": int, "msg": str}                       — on connect
      {"type": "vault_event", "path": str, "kind": str, "ts": str}  — vault watcher
      {"type": "agent.run", "phase": str, "agent": str, ...}        — agent lifecycle
      {"type": "approval", "agent": str, "tool": str, ...}          — approval needed
      {"type": "ping"}                                                — keepalive (30s)

    All real-time events flow through the event hub (backend.services.events).
    """
    await ws.accept()
    await ws.send_json({"type": "hello", "ts": _now(), "msg": "connected"})
    q = events.subscribe()
    try:
        while True:
            try:
                ev = await asyncio.wait_for(q.get(), timeout=30)
                await ws.send_json(ev)
            except asyncio.TimeoutError:
                await ws.send_json({"type": "ping"})
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        events.unsubscribe(q)


def _now() -> int:
    import time

    return int(time.time())




# ── Static file serving — the React webui is the app ──────────────
# This MUST be the last route registered: /{path:path} catches everything.
if FRONTEND_BUILD.exists():
    # Static assets (JS, CSS, fonts) from the Vite build.
    app.mount(
        "/_app",
        StaticFiles(directory=FRONTEND_BUILD / "_app"),
        name="app-assets",
    )

    @app.get("/")
    async def serve_index() -> FileResponse:
        return FileResponse(FRONTEND_BUILD / "index.html")

    @app.get("/{path:path}")
    async def serve_spa(path: str) -> FileResponse:
        # Serve any matching file in the webui build (assets). The app uses
        # HashRouter, so unknown paths fall back to index.html.
        file_path = FRONTEND_BUILD / path
        if file_path.is_file():
            return FileResponse(file_path)
        return FileResponse(FRONTEND_BUILD / "index.html")
else:
    @app.get("/")
    async def serve_index() -> JSONResponse:
        return JSONResponse(
            {"status": "no-frontend",
             "detail": "webui not built — run: cd webui && npm install && npm run build"}
        )
