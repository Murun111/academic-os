"""Multi-LLM hub — a single interface for every LLM backend on this machine.

Detects which CLIs/services are available, lists their models, and routes
chat calls to the chosen backend. Backends are pluggable; each implements
`probe()`, `models()`, and `chat(messages, model)`.

Backends supported today:
- ollama   — local HTTP, http://127.0.0.1:11434
- codex    — OpenAI Codex CLI (ChatGPT-authenticated)
- claude   — Anthropic Claude Code CLI (Anthropic-authenticated)
- gemini   — Google Gemini CLI (Google-authenticated)
- hermes   — local Hermes agent (this machine's primary)

Adding a new backend:
1. Subclass `Backend`
2. Add a `name` and implement the three methods
3. Add the instance to `BACKENDS` below
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import AsyncIterator


# ── Data shape ────────────────────────────────────────────────────────
@dataclass
class ModelInfo:
    id: str                       # e.g. "gpt-4o", "qwen3:30b-a3b", "claude-sonnet-4"
    label: str = ""               # human-friendly
    context: int = 0              # context window (0 if unknown)
    cost_per_mtok: float = 0.0    # cost per million tokens ($) — 0 for local/free


@dataclass
class ProbeResult:
    online: bool
    message: str = ""             # human-readable status
    account: str = ""             # who's logged in (e.g. "ChatGPT Plus", "Anthropic Pro")
    models: list[ModelInfo] = field(default_factory=list)
    latency_ms: int = 0


@dataclass
class ChatMessage:
    role: str                     # "user" | "assistant" | "system"
    content: str


@dataclass
class ChatResult:
    backend: str
    model: str
    content: str
    tokens: int = 0
    elapsed_ms: int = 0
    raw: dict = field(default_factory=dict)


# ── Base ──────────────────────────────────────────────────────────────
class Backend(ABC):
    name: str = "base"

    @abstractmethod
    async def probe(self) -> ProbeResult: ...

    @abstractmethod
    async def models(self) -> list[ModelInfo]: ...

    @abstractmethod
    async def chat(self, messages: list[ChatMessage], model: str = "") -> ChatResult: ...


# ── Helpers ───────────────────────────────────────────────────────────
def _run(cmd: list[str], timeout: int = 8, input_text: str | None = None) -> tuple[int, str, str]:
    """Run a command, return (exit_code, stdout, stderr)."""
    try:
        r = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
            input=input_text, env={**os.environ, "PATH": _augmented_path()},
        )
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        return 124, "", "timeout"
    except FileNotFoundError:
        return 127, "", f"command not found: {cmd[0]}"


def _augmented_path() -> str:
    """Some CLIs (notably the Codex desktop-app binary) live outside the
    default PATH. Append well-known user bin dirs so subprocesses find them."""
    extra = [
        str(Path.home() / ".local/bin"),
        str(Path.home() / "bin"),
        "/Applications/Codex.app/Contents/Resources",
    ]
    p = os.environ.get("PATH", "")
    return ":".join(extra) + ":" + p


def _http_get_json(url: str, timeout: int = 3) -> dict | None:
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except (urllib.error.URLError, json.JSONDecodeError, OSError):
        return None


# House style for the Chat tab, applied by app.py to every backend.
#
# The Chat bubble renders message content as PLAIN TEXT — there is no markdown
# parser in Chat.tsx. So a model emitting "### Tips" or "**bold**" puts literal
# hashes and asterisks on screen. Qwen3 does this constantly. Both halves of the
# rule matter: no markdown because nothing renders it, no emoji because this is
# a planning tool and not a social feed.
HOUSE_STYLE = (
    "You are the assistant inside Academic OS, a student planning app.\n"
    "Write in plain, complete English sentences and nothing else.\n"
    "Your output is displayed as raw text with no markdown rendering. Never "
    "use #, *, _, backticks, or --- for formatting. Never use headings, bold, "
    "or horizontal rules.\n"
    "Never use emoji, hashtags, arrows, or decorative symbols.\n"
    "If you must enumerate, write '1.' at the start of a line and keep each "
    "item to one sentence.\n"
    "Keep answers under 120 words. If you do not know something, say so "
    "plainly in one sentence rather than guessing.\n"
    "When the student asks about their own deadlines, courses, grades, or "
    "tasks, answer only from the data provided to you in context. Do not "
    "invent assignments, dates, or classes; if the answer is not in that "
    "data, say you do not have it and suggest where they can add it."
)


# ── Ollama ────────────────────────────────────────────────────────────
class OllamaBackend(Backend):
    name = "ollama"
    base = "http://127.0.0.1:11434"
    # Chat call timeout (s). Default 300 so slow local models (e.g. qwen3:30b in
    # the autonomous translation loop) don't hit a premature socket timeout.
    chat_timeout = float(os.environ.get("OLLAMA_TIMEOUT", "300"))

    async def probe(self) -> ProbeResult:
        t0 = time.time()
        d = _http_get_json(f"{self.base}/api/tags")
        ms = int((time.time() - t0) * 1000)
        if not d:
            # No Ollama — offer the bundled llama.cpp model if it's installed,
            # so the Chat picker shows something real instead of an empty list.
            from backend.services import local_llm
            if local_llm.binary_path() is not None and local_llm.installed_model() is not None:
                return ProbeResult(
                    online=True,
                    message="bundled local AI (llama.cpp)",
                    account="local",
                    models=[ModelInfo(id="local ai", label="Local AI (bundled)")],
                    latency_ms=ms,
                )
            return ProbeResult(online=False, message=f"not reachable at {self.base}")
        models = [ModelInfo(id=m["name"], label=m["name"],
                            context=m.get("details", {}).get("parameter_size", ""))
                  for m in d.get("models", [])
                  if "embed" not in m["name"].lower()]
        return ProbeResult(
            online=True,
            message=f"{len(models)} model(s) loaded",
            account="local",
            models=models,
            latency_ms=ms,
        )

    async def models(self) -> list[ModelInfo]:
        return (await self.probe()).models

    async def chat(self, messages: list[ChatMessage], model: str = "",
                   options: dict | None = None) -> ChatResult:
        if not model:
            raise ValueError("ollama: model is required")
        payload = {
            "model": model,
            "messages": [m.__dict__ for m in messages],
            "stream": False,
            "keep_alive": os.environ.get("OLLAMA_KEEP_ALIVE", "5m"),
        }
        if options:  # e.g. {"temperature": 0} for deterministic/greedy decoding
            payload["options"] = options
        body = json.dumps(payload).encode()
        req = urllib.request.Request(
            f"{self.base}/api/chat", data=body,
            headers={"Content-Type": "application/json"},
        )
        t0 = time.time()
        try:
            with urllib.request.urlopen(req, timeout=self.chat_timeout) as r:
                d = json.loads(r.read())
        except urllib.error.HTTPError as e:
            # Ollama IS running but rejected the request — almost always an
            # unknown model name. HTTPError subclasses URLError, so without
            # this clause it fell through to the bundled fallback below and
            # silently answered from the 0.5B model instead. A quiet downgrade
            # from qwen3:4b to a 0.5B reads as "the AI got stupid", with no
            # error anywhere. Surface it.
            try:
                detail = e.read().decode()[:200].strip()
            except Exception:
                detail = ""
            raise RuntimeError(
                f"ollama rejected model {model!r} (HTTP {e.code}): {detail}"
            ) from e
        except (urllib.error.URLError, ConnectionError):
            # Ollama not installed/running → bundled llama-server fallback,
            # same policy as OllamaService in backend/ollama.py.
            return await self._bundled_chat(messages, t0)
        elapsed = int((time.time() - t0) * 1000)
        return ChatResult(
            backend=self.name, model=model,
            content=d.get("message", {}).get("content", ""),
            tokens=d.get("eval_count", 0) + d.get("prompt_eval_count", 0),
            elapsed_ms=elapsed, raw=d,
        )

    async def _bundled_chat(self, messages: list[ChatMessage], t0: float) -> ChatResult:
        """Chat via the bundled llama.cpp server (OpenAI format)."""
        from backend.services import local_llm

        up = await asyncio.to_thread(local_llm.ensure_running)
        if not up:
            raise ConnectionError(
                "no local AI: Ollama absent and bundled model not installed"
            )
        # House style is injected by app.py so it applies to every backend, not
        # just this one — do not re-add it here or it lands twice.
        payload = {
            "model": "local",
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "stream": False,
            # llama-server defaults (temp 0.8) are far too loose for a 0.5B model.
            "temperature": 0.3,
            "top_p": 0.9,
            "repeat_penalty": 1.1,
            "max_tokens": 512,
        }
        req = urllib.request.Request(
            f"{local_llm.BASE_URL}/v1/chat/completions",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
        )

        def _post() -> dict:
            with urllib.request.urlopen(req, timeout=self.chat_timeout) as r:
                return json.loads(r.read())

        d = await asyncio.to_thread(_post)
        msg = (d.get("choices") or [{}])[0].get("message") or {}
        usage = d.get("usage") or {}
        return ChatResult(
            backend=self.name, model="local ai",
            content=msg.get("content", ""),
            tokens=usage.get("total_tokens", 0),
            elapsed_ms=int((time.time() - t0) * 1000), raw=d,
        )

    async def chat_stream(self, messages: list[ChatMessage], model: str = "",
                          options: dict | None = None) -> AsyncIterator[dict]:
        """Stream chat tokens from Ollama's NDJSON /api/chat, falling back to
        the bundled llama-server (same policy as chat()) when Ollama is
        unreachable.

        Yields dicts matching the app-wide SSE event contract:
        - {"delta": <text chunk>} for each content piece, as it arrives
        - {"done": true, "message": {role, content, backend, model, tokens,
          elapsed_ms}} once, at the end
        - {"error": <friendly message>} on failure (terminal — no further
          events follow)

        Streams incrementally: the blocking socket read runs in a worker
        thread and pushes each NDJSON line onto an asyncio.Queue as it
        arrives, so deltas reach the caller in real time rather than after
        the whole response has been read. Cancelling iteration (client
        disconnect) raises CancelledError out of this generator normally —
        it is not swallowed — so the caller can persist whatever partial
        text accumulated so far.
        """
        if not model:
            raise ValueError("ollama: model is required")
        payload = {
            "model": model,
            "messages": [m.__dict__ for m in messages],
            "stream": True,
            "keep_alive": os.environ.get("OLLAMA_KEEP_ALIVE", "5m"),
        }
        if options:
            payload["options"] = options
        body = json.dumps(payload).encode()
        req = urllib.request.Request(
            f"{self.base}/api/chat", data=body,
            headers={"Content-Type": "application/json"},
        )
        t0 = time.time()
        try:
            full = ""
            tokens = 0
            async for chunk in self._stream_ndjson(req, self.chat_timeout):
                piece = chunk.get("message", {}).get("content", "")
                if piece:
                    full += piece
                    yield {"delta": piece}
                if chunk.get("done"):
                    tokens = chunk.get("eval_count", 0) + chunk.get("prompt_eval_count", 0)
        except (urllib.error.URLError, ConnectionError):
            # Ollama not installed/running → bundled llama-server fallback,
            # same policy as chat()/_bundled_chat above.
            async for ev in self._bundled_chat_stream(messages, t0):
                yield ev
            return
        except urllib.error.HTTPError as e:
            try:
                detail = e.read().decode()[:200].strip()
            except Exception:
                detail = ""
            yield {"error": f"ollama rejected model {model!r} (HTTP {e.code}): {detail}"}
            return
        elapsed = int((time.time() - t0) * 1000)
        yield {"done": True, "message": {
            "role": "assistant", "content": full,
            "backend": self.name, "model": model,
            "tokens": tokens, "elapsed_ms": elapsed,
        }}

    async def _bundled_chat_stream(self, messages: list[ChatMessage], t0: float) -> AsyncIterator[dict]:
        """Stream chat via the bundled llama.cpp server (OpenAI SSE format).

        llama-server is OpenAI-compatible: POST /v1/chat/completions with
        stream:true returns 'data: {...}\\n\\n' lines and a final 'data:
        [DONE]' sentinel. Keeps the same sampling params as the non-streaming
        _bundled_chat above. House style is injected by app.py for every
        backend — not re-added here, same as _bundled_chat.
        """
        from backend.services import local_llm

        up = await asyncio.to_thread(local_llm.ensure_running)
        if not up:
            yield {"error": "no local AI: Ollama absent and bundled model not installed"}
            return
        payload = {
            "model": "local",
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "stream": True,
            "temperature": 0.3,
            "top_p": 0.9,
            "repeat_penalty": 1.1,
            "max_tokens": 512,
        }
        req = urllib.request.Request(
            f"{local_llm.BASE_URL}/v1/chat/completions",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
        )
        try:
            full = ""
            tokens = 0
            async for line in self._stream_sse_lines(req, self.chat_timeout):
                if line == "[DONE]":
                    break
                try:
                    chunk = json.loads(line)
                except json.JSONDecodeError:
                    continue
                choice = (chunk.get("choices") or [{}])[0]
                piece = (choice.get("delta") or {}).get("content", "")
                if piece:
                    full += piece
                    yield {"delta": piece}
                usage = chunk.get("usage") or {}
                if usage.get("total_tokens"):
                    tokens = usage["total_tokens"]
        except Exception as e:
            yield {"error": f"bundled AI stream error: {e}"}
            return
        elapsed = int((time.time() - t0) * 1000)
        yield {"done": True, "message": {
            "role": "assistant", "content": full,
            "backend": self.name, "model": "local ai",
            "tokens": tokens, "elapsed_ms": elapsed,
        }}

    @staticmethod
    async def _stream_ndjson(req: urllib.request.Request, timeout: float) -> AsyncIterator[dict]:
        """Read a line-delimited-JSON HTTP response incrementally.

        Runs the blocking urlopen()/readline() loop in a worker thread and
        relays each parsed line to the calling coroutine via an
        asyncio.Queue, so callers see chunks as they arrive rather than
        after the whole body has been buffered. Connection errors raised
        while opening the request propagate to the caller so it can decide
        how to handle them (e.g. fall back to another backend).
        """
        loop = asyncio.get_event_loop()
        queue: asyncio.Queue = asyncio.Queue()
        _DONE = object()
        # fut.cancel() is a no-op once the executor thread is running, so a
        # client disconnect used to leave the model generating to completion.
        # The stop event + closing the response from the finally block unblock
        # the worker's read; the server sees the closed socket and halts.
        stop = threading.Event()
        resp_box: list = []

        def _producer():
            try:
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    resp_box.append(r)
                    for line in r:
                        if stop.is_set():
                            break
                        if line.strip():
                            try:
                                parsed = json.loads(line)
                            except json.JSONDecodeError:
                                continue
                            loop.call_soon_threadsafe(queue.put_nowait, parsed)
            except Exception as e:
                if not stop.is_set():
                    loop.call_soon_threadsafe(queue.put_nowait, ("__error__", e))
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, _DONE)

        fut = loop.run_in_executor(None, _producer)
        try:
            while True:
                item = await queue.get()
                if item is _DONE:
                    break
                if isinstance(item, tuple) and item and item[0] == "__error__":
                    raise item[1]
                yield item
        finally:
            stop.set()
            for r in resp_box:
                try:
                    r.close()
                except Exception:
                    pass
            if not fut.done():
                fut.cancel()

    @staticmethod
    async def _stream_sse_lines(req: urllib.request.Request, timeout: float) -> AsyncIterator[str]:
        """Read an OpenAI-style SSE response ('data: ...' lines) incrementally,
        stripped of the 'data: ' prefix. Same worker-thread relay pattern as
        _stream_ndjson, including the disconnect-cancellation contract."""
        loop = asyncio.get_event_loop()
        queue: asyncio.Queue = asyncio.Queue()
        _DONE = object()
        stop = threading.Event()
        resp_box: list = []

        def _producer():
            try:
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    resp_box.append(r)
                    for raw in r:
                        if stop.is_set():
                            break
                        line = raw.decode("utf-8", errors="replace").strip()
                        if not line or line.startswith(":"):
                            continue
                        if line.startswith("data: "):
                            line = line[len("data: "):]
                        loop.call_soon_threadsafe(queue.put_nowait, line)
            except Exception as e:
                if not stop.is_set():
                    loop.call_soon_threadsafe(queue.put_nowait, ("__error__", e))
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, _DONE)

        fut = loop.run_in_executor(None, _producer)
        try:
            while True:
                item = await queue.get()
                if item is _DONE:
                    break
                if isinstance(item, tuple) and item and item[0] == "__error__":
                    raise item[1]
                yield item
        finally:
            stop.set()
            for r in resp_box:
                try:
                    r.close()
                except Exception:
                    pass
            if not fut.done():
                fut.cancel()


# ── Codex (CLI) ───────────────────────────────────────────────────────
class CodexBackend(Backend):
    name = "codex"
    binary_known_paths = [
        "/Applications/Codex.app/Contents/Resources/codex",
        str(Path.home() / "bin" / "codex"),
    ]

    def _binary(self) -> str | None:
        # Check well-known paths first, then fall back to PATH.
        for p in self.binary_known_paths:
            if Path(p).is_file() and os.access(p, os.X_OK):
                return p
        return shutil.which("codex")

    async def probe(self) -> ProbeResult:
        binary = self._binary()
        if not binary:
            return ProbeResult(online=False, message="codex CLI not installed")
        t0 = time.time()
        rc, out, err = _run([binary, "login", "status"], timeout=6)
        ms = int((time.time() - t0) * 1000)
        if rc != 0:
            return ProbeResult(online=False, message=f"auth check failed: {(err or out).strip()[:80]}")
        # Login status output: "Logged in using ChatGPT" / "Logged in using
        # API key" — newer codex versions print it to STDERR, so check both.
        status_text = out + err
        if "ChatGPT" in status_text:
            auth_kind = "ChatGPT"
        elif "API" in status_text:
            auth_kind = "API key"
        else:
            auth_kind = "unknown"
        models = self._models_for_auth(auth_kind)
        return ProbeResult(
            online=True, message="ok",
            account=auth_kind, models=models, latency_ms=ms,
        )

    async def models(self) -> list[ModelInfo]:
        return (await self.probe()).models

    @staticmethod
    def _models_for_auth(auth_kind: str) -> list[ModelInfo]:
        # ChatGPT-authenticated Codex doesn't expose model selection via
        # the CLI — the model is determined by your ChatGPT plan. Show
        # a single "default" entry; any model string passed is ignored.
        if auth_kind == "API key":
            return [
                ModelInfo("gpt-4.1", "GPT-4.1", 1_000_000),
                ModelInfo("gpt-4.1-mini", "GPT-4.1 mini", 1_000_000),
                ModelInfo("gpt-4o", "GPT-4o", 128_000),
                ModelInfo("gpt-4o-mini", "GPT-4o mini", 128_000),
                ModelInfo("o3", "o3", 200_000),
                ModelInfo("o3-mini", "o3 mini", 200_000),
                ModelInfo("o4-mini", "o4 mini", 200_000),
            ]
        return [ModelInfo("default", "ChatGPT default (plan model)", 0)]

    async def chat(self, messages: list[ChatMessage], model: str = "") -> ChatResult:
        binary = self._binary()
        if not binary:
            raise RuntimeError("codex CLI not available")
        # Flatten the messages into a single prompt — codex exec is one-shot.
        prompt = "\n\n".join(
            f"[{m.role}]\n{m.content}" for m in messages if m.role != "system"
        )
        t0 = time.time()
        # Determine auth kind so we can decide whether to pass -m. ChatGPT
        # auth rejects all model strings ("not supported"), so only pass -m
        # for confirmed API-key auth; unknown auth gets the safe no-flag path.
        probe = await self.probe()
        if probe.account == "API key":
            if not model:
                model = "gpt-4.1-mini"
            args = [binary, "exec", "--skip-git-repo-check", "-m", model, "--", prompt]
        else:
            args = [binary, "exec", "--skip-git-repo-check", "--", prompt]
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            env={**os.environ, "PATH": _augmented_path()},
        )
        try:
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=180)
        except asyncio.TimeoutError:
            proc.kill()
            raise RuntimeError("codex timed out after 180s")
        elapsed = int((time.time() - t0) * 1000)
        content = out.decode("utf-8", errors="replace").strip()
        # Strip the trailing "tokens used\nNNN\n..." summary line so the
        # chat UI doesn't show codex's bookkeeping.
        lines = content.splitlines()
        cleaned = []
        for line in lines:
            if (line.strip().replace(",", "").isdigit()
                    and cleaned and cleaned[-1].strip() == "tokens used"):
                cleaned.pop()
                continue
            if line.startswith("hook:"):
                continue
            cleaned.append(line)
        content = "\n".join(cleaned).strip()
        tokens = len(content) // 4
        return ChatResult(
            backend=self.name, model=model or "default",
            content=content, tokens=tokens, elapsed_ms=elapsed,
        )


# ── Claude Code (CLI) ─────────────────────────────────────────────────
class ClaudeBackend(Backend):
    name = "claude"

    def _binary(self) -> str | None:
        return shutil.which("claude")

    async def probe(self) -> ProbeResult:
        binary = self._binary()
        if not binary:
            return ProbeResult(online=False, message="claude CLI not installed")
        # Verify the binary actually works AND the user is authenticated.
        t0 = time.time()
        rc, out, err = _run([binary, "--version"], timeout=4)
        if rc != 0:
            return ProbeResult(online=False, message=f"binary error: {err.strip()[:80]}")
        # Auth check: on macOS the OAuth token lands in Keychain (not on disk
        # as ~/.claude/.credentials.json like the older CLI did), and on
        # Linux the same applies via the system secret service. The reliable
        # cross-platform check is `claude auth status` — exit 0 means a
        # valid credential was found (Keychain / keyring / API key, depending
        # on auth method). The status JSON also tells us which account is
        # signed in and via what method, which is useful for the UI.
        rc, out, err = _run([binary, "auth", "status"], timeout=6)
        if rc != 0:
            return ProbeResult(
                online=False,
                message=f"claude installed but not authenticated (auth status exit {rc})",
            )
        # Parse the JSON to surface the account + method in the ProbeResult
        # so the MoA panel and the /api/llms/status endpoint can show it.
        account = "Anthropic"
        try:
            import json as _json
            status = _json.loads(out)
            if status.get("email"):
                account = f"{status['email']} ({status.get('authMethod', '?')}, "
                account += f"{status.get('subscriptionType', status.get('apiProvider', '?'))})"
        except (ValueError, KeyError):
            pass  # fall back to default account string
        ms = int((time.time() - t0) * 1000)
        models = [
            ModelInfo("claude-sonnet-5", "Claude Sonnet 5", 1_000_000),
            ModelInfo("claude-opus-4-8", "Claude Opus 4.8 (1M)", 1_000_000),
            ModelInfo("claude-sonnet-4-5", "Claude Sonnet 4.5", 200_000),
            ModelInfo("claude-opus-4-1", "Claude Opus 4.1", 200_000),
            ModelInfo("claude-haiku-4-5", "Claude Haiku 4.5", 200_000),
        ]
        return ProbeResult(
            online=True, message="ok", account=account,
            models=models, latency_ms=ms,
        )

    async def models(self) -> list[ModelInfo]:
        return (await self.probe()).models

    async def chat(self, messages: list[ChatMessage], model: str = "") -> ChatResult:
        binary = self._binary()
        if not binary:
            raise RuntimeError("claude CLI not available")
        if not model:
            model = "claude-sonnet-5"
        # `claude -p` is the non-interactive print mode.
        prompt = "\n\n".join(
            f"[{m.role}]\n{m.content}" for m in messages if m.role != "system"
        )
        t0 = time.time()
        proc = await asyncio.create_subprocess_exec(
            binary, "-p", "--model", model, prompt,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout=180)
        except asyncio.TimeoutError:
            proc.kill()
            raise RuntimeError("claude timed out after 180s")
        elapsed = int((time.time() - t0) * 1000)
        content = out.decode("utf-8", errors="replace").strip()
        if not content and err:
            content = f"(claude stderr) {err.decode('utf-8', errors='replace')[:500]}"
        return ChatResult(
            backend=self.name, model=model,
            content=content, tokens=len(content) // 4, elapsed_ms=elapsed,
        )


# ── Droid (CLI) — Factory's coding agent ────────────────────────────
class DroidBackend(Backend):
    name = "droid"

    def _binary(self) -> str | None:
        return shutil.which("droid")

    async def probe(self) -> ProbeResult:
        binary = self._binary()
        if not binary:
            return ProbeResult(online=False, message="droid CLI not installed")
        t0 = time.time()
        rc, out, err = _run([binary, "--version"], timeout=4)
        ms = int((time.time() - t0) * 1000)
        if rc != 0:
            return ProbeResult(online=False, message=f"binary error: {err.strip()[:80]}")
        # Droid is Factory's coding agent — it brings its own model fleet.
        models = [
            ModelInfo("sonnet-4.5", "Sonnet 4.5 (Factory)", 200_000),
            ModelInfo("opus-4.1", "Opus 4.1 (Factory)", 200_000),
            ModelInfo("gpt-5", "GPT-5 (Factory)", 400_000),
        ]
        return ProbeResult(
            online=True, message="ok", account="Factory",
            models=models, latency_ms=ms,
        )

    async def models(self) -> list[ModelInfo]:
        return (await self.probe()).models

    async def chat(self, messages: list[ChatMessage], model: str = "") -> ChatResult:
        binary = self._binary()
        if not binary:
            raise RuntimeError("droid CLI not available")
        if not model:
            model = "sonnet-4.5"
        prompt = "\n\n".join(
            f"[{m.role}]\n{m.content}" for m in messages if m.role != "system"
        )
        t0 = time.time()
        proc = await asyncio.create_subprocess_exec(
            binary, "-m", model, prompt,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout=180)
        except asyncio.TimeoutError:
            proc.kill()
            raise RuntimeError("droid timed out after 180s")
        elapsed = int((time.time() - t0) * 1000)
        content = out.decode("utf-8", errors="replace").strip()
        if not content and err:
            content = f"(droid stderr) {err.decode('utf-8', errors='replace')[:500]}"
        return ChatResult(
            backend=self.name, model=model,
            content=content, tokens=len(content) // 4, elapsed_ms=elapsed,
        )


# ── Cursor Agent (CLI) — Cursor's coding agent ───────────────────────
class CursorBackend(Backend):
    name = "cursor"

    def _binary(self) -> str | None:
        return shutil.which("agent")

    async def probe(self) -> ProbeResult:
        binary = self._binary()
        if not binary:
            return ProbeResult(online=False, message="cursor agent CLI not installed")
        t0 = time.time()
        rc, out, err = _run([binary, "--version"], timeout=4)
        ms = int((time.time() - t0) * 1000)
        if rc != 0:
            return ProbeResult(online=False, message=f"binary error: {err.strip()[:80]}")
        # Cursor's CLI uses Cursor's model fleet (frontier LLMs via Cursor).
        models = [
            ModelInfo("composer-1", "Composer 1 (Cursor)", 200_000),
            ModelInfo("sonnet-4.5", "Sonnet 4.5 (Cursor)", 200_000),
            ModelInfo("gpt-5", "GPT-5 (Cursor)", 400_000),
        ]
        return ProbeResult(
            online=True, message="ok", account="Cursor",
            models=models, latency_ms=ms,
        )

    async def models(self) -> list[ModelInfo]:
        return (await self.probe()).models

    async def chat(self, messages: list[ChatMessage], model: str = "") -> ChatResult:
        binary = self._binary()
        if not binary:
            raise RuntimeError("cursor agent CLI not available")
        if not model:
            model = "composer-1"
        prompt = "\n\n".join(
            f"[{m.role}]\n{m.content}" for m in messages if m.role != "system"
        )
        t0 = time.time()
        proc = await asyncio.create_subprocess_exec(
            binary, "--model", model, prompt,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout=180)
        except asyncio.TimeoutError:
            proc.kill()
            raise RuntimeError("cursor timed out after 180s")
        elapsed = int((time.time() - t0) * 1000)
        content = out.decode("utf-8", errors="replace").strip()
        if not content and err:
            content = f"(cursor stderr) {err.decode('utf-8', errors='replace')[:500]}"
        return ChatResult(
            backend=self.name, model=model,
            content=content, tokens=len(content) // 4, elapsed_ms=elapsed,
        )


# ── Gemini (CLI) — Google's large-context analyst ────────────────────
class GeminiBackend(Backend):
    """Google Gemini via the `gemini` CLI (1M-token context — the analyst).

    NOTE: as of 2026 Google retired the *free* individual Gemini-CLI tier
    (`IneligibleTierError` — "migrate to the Antigravity suite"). So this
    backend is only usable with an API key. We probe honestly: online ONLY
    when GEMINI_API_KEY / GOOGLE_API_KEY is set, otherwise offline with the
    migration message — never a false "online" that fails on first chat.
    """
    name = "gemini"

    def _binary(self) -> str | None:
        return shutil.which("gemini")

    _KEY_VARS = ("GEMINI_API_KEY", "GOOGLE_API_KEY", "GOOGLE_GENAI_API_KEY")

    def _api_key(self) -> str | None:
        for var in self._KEY_VARS:
            if os.environ.get(var):
                return os.environ[var]
        # Fallback: backend/.env — this app loads secrets per-service via
        # dotenv_values (never into os.environ), so check the file directly.
        try:
            from dotenv import dotenv_values
            env = dotenv_values(Path(__file__).parent / ".env")
            for var in self._KEY_VARS:
                if env.get(var):
                    return env[var]
        except ImportError:
            pass
        return None

    async def probe(self) -> ProbeResult:
        binary = self._binary()
        if not binary:
            return ProbeResult(online=False, message="gemini CLI not installed")
        if not self._api_key():
            return ProbeResult(
                online=False,
                message="free tier retired (IneligibleTierError) — set GEMINI_API_KEY or use Antigravity",
            )
        t0 = time.time()
        rc, out, err = _run([binary, "--version"], timeout=4)
        ms = int((time.time() - t0) * 1000)
        if rc != 0:
            return ProbeResult(online=False, message=f"binary error: {err.strip()[:80]}")
        models = [
            ModelInfo("gemini-2.5-pro", "Gemini 2.5 Pro (1M ctx)", 1_000_000),
            ModelInfo("gemini-2.5-flash", "Gemini 2.5 Flash (1M ctx)", 1_000_000),
        ]
        return ProbeResult(online=True, message="ok", account="Google (API key)",
                           models=models, latency_ms=ms)

    async def models(self) -> list[ModelInfo]:
        return (await self.probe()).models

    async def chat(self, messages: list[ChatMessage], model: str = "") -> ChatResult:
        binary = self._binary()
        if not binary:
            raise RuntimeError("gemini CLI not available")
        if not model:
            model = "gemini-2.5-flash"
        prompt = "\n\n".join(
            f"[{m.role}]\n{m.content}" for m in messages if m.role != "system"
        )
        env = {**os.environ, "PATH": _augmented_path()}
        key = self._api_key()
        if key and not env.get("GEMINI_API_KEY"):
            env["GEMINI_API_KEY"] = key  # key may come from backend/.env
        t0 = time.time()
        proc = await asyncio.create_subprocess_exec(
            binary, "-p", prompt, "-m", model,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout=180)
        except asyncio.TimeoutError:
            proc.kill()
            raise RuntimeError("gemini timed out after 180s")
        elapsed = int((time.time() - t0) * 1000)
        content = out.decode("utf-8", errors="replace").strip()
        if not content and err:
            content = f"(gemini stderr) {err.decode('utf-8', errors='replace')[:500]}"
        return ChatResult(backend=self.name, model=model,
                          content=content, tokens=len(content) // 4, elapsed_ms=elapsed)


# ── Hermes (local) ────────────────────────────────────────────────────
class HermesBackend(Backend):
    """Routes calls to the running Hermes agent via the agentic OS."""
    name = "hermes"

    async def probe(self) -> ProbeResult:
        # Hermes is always online if this module is loaded — it IS the runtime.
        return ProbeResult(
            online=True, message="primary", account="local",
            models=[ModelInfo("hermes-mini-m3", "Hermes Mini M3 (local)", 0)],
        )

    async def models(self) -> list[ModelInfo]:
        return [ModelInfo("hermes-mini-m3", "Hermes Mini M3 (local)", 0)]

    async def chat(self, messages: list[ChatMessage], model: str = "") -> ChatResult:
        # One-shot call to the hermes CLI via _run.
        # Flatten messages into a single prompt (skip system messages).
        prompt = "\n\n".join(
            f"[{m.role}]\n{m.content}" for m in messages if m.role != "system"
        )
        # Build argv: hermes -z <prompt> --safe-mode [optional -m <model>]
        argv = ["hermes", "-z", prompt, "--safe-mode"]
        if model and model != "hermes-mini-m3":
            argv.insert(2, "-m")
            argv.insert(3, model)
        # Call the _run helper with 180s timeout.
        t0 = time.time()
        code, out, err = _run(argv, timeout=180)
        elapsed = int((time.time() - t0) * 1000)
        # Error handling: non-zero exit or empty output.
        if code != 0 or not out.strip():
            error_msg = err.strip() or out.strip()
            raise RuntimeError(f"hermes failed (exit {code}): {error_msg}")
        # Return ChatResult.
        return ChatResult(
            backend=self.name,
            model=model or "hermes-mini-m3",
            content=out.strip(),
            elapsed_ms=elapsed,
        )


# ── Nous Portal (cloud) ───────────────────────────────────────────────
class NousBackend(Backend):
    """Nous Research's inference API (inference-api.nousresearch.com).

    This is the cloud token-budget surface: 270+ models behind one OAuth login
    (free tiers, paid tiers, latest-aliases), OpenAI-compatible chat API.
    Credentials come from ~/.hermes/auth.json via hermes_cli.auth, which
    handles JWT refresh, expiry, and persistence — we just call the resolver
    on every chat/probe and trust it.

    The model list is fetched live on first probe and cached for NOUS_CACHE_S
    seconds so the dashboard's polling /api/llms/status doesn't hammer the
    upstream. Cache invalidates on TTL expiry; no manual flush.
    """
    name = "nous"
    base = "https://inference-api.nousresearch.com/v1"
    _cache_lock = None  # initialized lazily on first probe
    _cached_models: list[ModelInfo] = []
    _cached_at: float = 0.0
    NOUS_CACHE_S = 300  # 5 min — respects upstream while staying fresh

    def _ensure_lock(self):
        import threading
        if NousBackend._cache_lock is None:
            NousBackend._cache_lock = threading.Lock()
        return NousBackend._cache_lock

    @property
    def _log(self):
        import logging
        # Lazy so we don't need a module-level logger just for two warnings.
        return logging.getLogger(f"{__name__}.NousBackend")

    def _creds(self) -> dict | None:
        """Resolve a fresh Nous OAuth JWT. Returns None on any auth error.

        Never raises — auth problems are reported as offline in the probe, not
        as a 500 to the caller. Chat calls raise their own clear errors.

        The hermes_cli package lives at ~/.hermes/hermes-agent/. In the
        agentic-os venv it's on sys.path via a .pth file when launched from
        a normal shell, but the launchd-managed uvicorn process may have a
        stripped sys.path. We add the path defensively so we work in both.
        """
        try:
            import sys
            from pathlib import Path as _P
            hermes_root = str(_P.home() / ".hermes" / "hermes-agent")
            if hermes_root not in sys.path and _P(hermes_root).is_dir():
                sys.path.insert(0, hermes_root)
            from hermes_cli.auth import resolve_nous_runtime_credentials
            return resolve_nous_runtime_credentials()
        except Exception as exc:
            # self._log may also fail if logging is misconfigured in some
            # embedded contexts; fall back to a no-op logger.
            try:
                self._log.warning("nous: creds unavailable: %s", exc)
            except Exception:
                pass
            return None

    async def probe(self) -> ProbeResult:
        t0 = time.time()
        # _creds() is contracted never to raise (it catches internally and
        # returns None on auth failure), but we wrap defensively so a future
        # change in the auth resolver can't crash /api/llms/status.
        try:
            c = self._creds()
        except Exception as exc:
            return ProbeResult(
                online=False,
                message=f"nous auth resolver crashed: {type(exc).__name__}: {str(exc)[:80]}",
                latency_ms=int((time.time() - t0) * 1000),
            )
        if not c:
            return ProbeResult(
                online=False,
                message="nous not authenticated — `hermes auth status nous` to check",
                latency_ms=int((time.time() - t0) * 1000),
            )
        # Liveness check + cache warm-up in one round-trip: hit /v1/models
        # with the JWT, and if it's 200, use that same response to populate
        # the model cache. No second network call needed.
        try:
            loop = asyncio.get_event_loop()
            req = urllib.request.Request(
                f"{self.base}/models",
                headers={"Authorization": f"Bearer {c['api_key']}"},
            )
            def _hit():
                with urllib.request.urlopen(req, timeout=8) as r:
                    return r.status, json.loads(r.read())
            status, body = await loop.run_in_executor(None, _hit)
        except Exception as exc:
            return ProbeResult(
                online=False,
                message=f"nous reachable but auth failed: {type(exc).__name__}: {str(exc)[:80]}",
                latency_ms=int((time.time() - t0) * 1000),
            )
        if status != 200:
            return ProbeResult(
                online=False,
                message=f"nous /v1/models returned HTTP {status}",
                latency_ms=int((time.time() - t0) * 1000),
            )
        # Reuse the liveness response to warm the cache. Only refresh if
        # stale — we don't want the probe alone to invalidate an existing
        # cache (which the cache tests verify).
        now = time.time()
        if (now - NousBackend._cached_at) >= self.NOUS_CACHE_S:
            items = body.get("data", body)
            NousBackend._cached_models = [
                ModelInfo(
                    id=m.get("id", ""),
                    label=m.get("id", ""),
                    context=m.get("context_length", 0) or 0,
                )
                for m in items
                if isinstance(m, dict) and m.get("id")
            ]
            NousBackend._cached_at = now
        ms = int((time.time() - t0) * 1000)
        models = list(NousBackend._cached_models)
        n = len(models) or len(body.get("data", body))
        return ProbeResult(
            online=True,
            message=f"{n} models",
            account="Nous Portal (OAuth)",
            latency_ms=ms,
            models=models,
        )

    async def _maybe_refresh_models(self, c: dict | None) -> None:
        """Refresh the model list cache if it's older than NOUS_CACHE_S.

        Skips the upstream call when fresh. Acquires the lock to avoid
        thundering-herd refreshes when many workers boot at once.
        """
        now = time.time()
        if (now - NousBackend._cached_at) < self.NOUS_CACHE_S and NousBackend._cached_models:
            return
        if c is None:
            c = self._creds()
        if not c:
            return
        with self._ensure_lock():
            # Double-check inside the lock (another thread may have refreshed).
            if (time.time() - NousBackend._cached_at) < self.NOUS_CACHE_S and NousBackend._cached_models:
                return
            loop = asyncio.get_event_loop()
            def _fetch():
                req = urllib.request.Request(
                    f"{self.base}/models",
                    headers={"Authorization": f"Bearer {c['api_key']}"},
                )
                with urllib.request.urlopen(req, timeout=10) as r:
                    return json.loads(r.read())
            try:
                body = await loop.run_in_executor(None, _fetch)
                items = body.get("data", body)
                NousBackend._cached_models = [
                    ModelInfo(
                        id=m.get("id", ""),
                        label=m.get("id", ""),
                        context=m.get("context_length", 0) or 0,
                    )
                    for m in items
                    if isinstance(m, dict) and m.get("id")
                ]
                NousBackend._cached_at = time.time()
            except Exception as exc:
                self._log.warning("nous: model list refresh failed: %s", exc)
                # Leave the cache alone on failure — stale > empty.

    async def models(self) -> list[ModelInfo]:
        c = self._creds()
        if c is None:
            return NousBackend._cached_models  # may be empty
        await self._maybe_refresh_models(c)
        return list(NousBackend._cached_models)

    async def chat(self, messages: list[ChatMessage], model: str = "") -> ChatResult:
        if not model:
            # Pick a sensible default — the latest Claude (what this chat is).
            model = "anthropic/claude-fable-5"
        c = self._creds()
        if not c:
            raise RuntimeError(
                "nous: no credentials — `hermes auth status nous` to check, "
                "or re-login via `hermes login --provider nous`"
            )
        payload = {
            "model": model,
            "messages": [m.__dict__ for m in messages],
            "stream": False,
        }
        body = json.dumps(payload).encode()
        loop = asyncio.get_event_loop()
        def _post():
            req = urllib.request.Request(
                f"{self.base}/chat/completions",
                data=body,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {c['api_key']}",
                },
            )
            with urllib.request.urlopen(req, timeout=180) as r:
                return json.loads(r.read())
        t0 = time.time()
        try:
            data = await loop.run_in_executor(None, _post)
        except urllib.error.HTTPError as exc:
            # Surface upstream's error message (rate limit, model not found, etc.)
            err_body = ""
            try:
                err_body = exc.read().decode("utf-8", errors="replace")[:500]
            except Exception:
                pass
            raise RuntimeError(f"nous HTTP {exc.code}: {err_body}") from exc
        elapsed = int((time.time() - t0) * 1000)
        # OpenAI-compatible response: choices[0].message.content
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError(f"nous: unexpected response shape: {exc}: {str(data)[:300]}")
        usage = data.get("usage", {}) or {}
        tokens = int(usage.get("total_tokens", 0) or 0)
        return ChatResult(
            backend=self.name,
            model=model,
            content=content or "",
            tokens=tokens,
            elapsed_ms=elapsed,
            raw=data,
        )

    async def chat_stream(self, messages: list[ChatMessage], model: str = "") -> AsyncIterator[dict]:
        """Stream chat tokens from Nous Portal via SSE (server-sent events).
        
        Yields dicts like {"token": "<piece>"} for each content chunk.
        On completion, yields {"done": True, "content": "<full>", "tokens": N}.
        On error, yields {"error": "<msg>"}.
        """
        if not model:
            model = "anthropic/claude-fable-5"
        c = self._creds()
        if not c:
            raise RuntimeError(
                "nous: no credentials — `hermes auth status nous` to check, "
                "or re-login via `hermes login --provider nous`"
            )
        payload = {
            "model": model,
            "messages": [m.__dict__ for m in messages],
            "stream": True,
        }
        body = json.dumps(payload).encode()
        loop = asyncio.get_event_loop()

        # Execute the streaming request in an executor (urllib doesn't have native async)
        def _stream():
            req = urllib.request.Request(
                f"{self.base}/chat/completions",
                data=body,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {c['api_key']}",
                },
            )
            with urllib.request.urlopen(req, timeout=180) as r:
                # Read SSE stream line-by-line
                for line in r:
                    line_str = line.decode("utf-8", errors="replace").strip()
                    if not line_str or line_str.startswith(":"):
                        continue
                    if line_str.startswith("data: "):
                        line_str = line_str[6:]  # Strip "data: " prefix
                    if line_str == "[DONE]":
                        break
                    try:
                        chunk = json.loads(line_str)
                        yield chunk
                    except json.JSONDecodeError:
                        continue

        full_content = ""
        total_tokens = 0

        try:
            async for chunk in self._async_iterate(_stream, loop):
                # OpenAI-compatible streaming: choices[0].delta.content
                try:
                    delta = chunk.get("choices", [{}])[0].get("delta", {})
                    piece = delta.get("content", "")
                    if piece:
                        full_content += piece
                        yield {"token": piece}
                except (KeyError, IndexError, TypeError):
                    pass
                # Update token count from usage if available (some backends send it per chunk)
                usage = chunk.get("usage", {})
                if usage and "total_tokens" in usage:
                    total_tokens = int(usage.get("total_tokens", 0) or 0)
            yield {"done": True, "content": full_content, "tokens": total_tokens}
        except Exception as e:
            yield {"error": str(e)}

    @staticmethod
    async def _async_iterate(generator_func, loop):
        """Convert a blocking generator into an async iterator."""
        def _run():
            try:
                return list(generator_func())
            except Exception as e:
                return [e]
        items = await loop.run_in_executor(None, _run)
        for item in items:
            if isinstance(item, Exception):
                raise item
            yield item


# ── Registry ──────────────────────────────────────────────────────────
BACKENDS: list[Backend] = [
    OllamaBackend(),
    CodexBackend(),
    ClaudeBackend(),
    DroidBackend(),
    CursorBackend(),
    GeminiBackend(),
    HermesBackend(),
    NousBackend(),
]


async def status_all() -> dict[str, ProbeResult]:
    """Probe every backend in parallel and return a {name: ProbeResult} map."""
    results: list[ProbeResult | BaseException] = list(await asyncio.gather(
        *(b.probe() for b in BACKENDS),
        return_exceptions=True,
    ))
    out: dict[str, ProbeResult] = {}
    for backend, r in zip(BACKENDS, results):
        if isinstance(r, BaseException):
            out[backend.name] = ProbeResult(online=False, message=f"probe error: {r}")
        else:
            out[backend.name] = r
    return out


def get_backend(name: str) -> Backend:
    for b in BACKENDS:
        if b.name == name:
            return b
    raise KeyError(f"unknown backend: {name}")


# ── Thread history (persistent) ──────────────────────────────────────
# Lightweight JSON-on-disk store. Each thread is one file in
# ~/.agentic-os/llm_threads/<id>.json. SQLite would be overkill for the
# volume (a few hundred threads max); files are easier to grep, back up,
# and inspect with the existing vault tools.

import json as _json
from pathlib import Path as _Path

# Test override; None → resolved into the app data root via backend.vault.
# (Was hardcoded to ~/.agentic-os/ — a fork leftover that kept chat threads
# outside the data root, invisible to backup/restore. Never reintroduce.)
THREADS_DIR: _Path | None = None


def _threads_dir() -> _Path:
    if THREADS_DIR is not None:
        return THREADS_DIR
    from backend.vault import agentic_os_dir

    return agentic_os_dir() / "data" / "llm_threads"


def _ensure_dir() -> None:
    _threads_dir().mkdir(parents=True, exist_ok=True)


def _new_thread_id() -> str:
    import uuid as _uuid
    return _uuid.uuid4().hex[:12]


def _thread_path(tid: str) -> _Path:
    # Defensive: refuse path traversal.
    if "/" in tid or ".." in tid or not tid:
        raise ValueError("invalid thread id")
    return _threads_dir() / f"{tid}.json"


def list_threads() -> list[dict]:
    _ensure_dir()
    out: list[dict] = []
    for p in sorted(_threads_dir().glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
        try:
            d = _json.loads(p.read_text())
            out.append({
                "id": d["id"],
                "title": d.get("title", ""),
                "created_at": d.get("created_at", ""),
                "backend": d.get("backend", ""),
                "model": d.get("model", ""),
                "turns": len(d.get("messages", [])),
            })
        except (KeyError, _json.JSONDecodeError, OSError):
            continue
    return out


def get_thread(tid: str) -> dict | None:
    p = _thread_path(tid)
    if not p.is_file():
        return None
    return _json.loads(p.read_text())


def save_thread(tid: str | None, backend: str, model: str,
                user_text: str, assistant_text: str,
                assistant_meta: dict | None = None) -> str:
    """Append a user/assistant turn to a thread (creating it if needed).
    Returns the thread id."""
    _ensure_dir()
    if tid:
        thread = get_thread(tid) or _new_thread(tid, backend, model, user_text)
    else:
        tid = _new_thread_id()
        thread = _new_thread(tid, backend, model, user_text)
    thread["messages"].append({
        "role": "user",
        "content": user_text,
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    })
    thread["messages"].append({
        "role": "assistant",
        "content": assistant_text,
        "backend": backend,
        "model": model,
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        **(assistant_meta or {}),
    })
    thread["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    _thread_path(tid).write_text(_json.dumps(thread, indent=2))
    return tid


def _new_thread(tid: str, backend: str, model: str, first_user_text: str) -> dict:
    title = first_user_text[:60].replace("\n", " ").strip()
    return {
        "id": tid,
        "title": title,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "backend": backend,
        "model": model,
        "messages": [],
    }
