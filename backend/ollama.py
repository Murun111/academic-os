"""Ollama LLM service.

Local-first LLM. Default model is gemma4:latest. All agent calls go through
chat() which sends to Ollama's /api/chat endpoint. Supports streaming,
tool calls, and thinking mode.

Why Ollama, not the Anthropic SDK directly:
- Local. The dashboard reads calendar, projects, money — all sensitive.
- Free. The daily-brief runs every morning at 06:30; cumulative cost matters.
- Same API as Ollama Pro (which is just a managed-tier cloud add-on).

The cold-start penalty is ~12s on first call. The agent runner warms the
model via warm_model() at startup.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Optional

import httpx


@dataclass
class ToolCall:
    """One tool invocation request from the model."""

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class ChatMessage:
    """A message in a chat conversation."""

    role: str  # "user" | "assistant" | "tool" | "system"
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_call_id: Optional[str] = None  # for role="tool" replies


@dataclass
class ChatResponse:
    """Non-streaming chat response."""

    message: ChatMessage
    model: str
    total_duration_ns: int
    prompt_eval_count: int
    eval_count: int
    done_reason: str

    @property
    def duration_seconds(self) -> float:
        return self.total_duration_ns / 1e9


def _default_base_url() -> str:
    return os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")


def _default_model() -> str:
    # gemma4 (~9.6GB) is the default: small enough to stay resident on a 32GB
    # Mac alongside other apps without forcing swap (qwen3 at ~21GB caused heavy
    # paging). Tool-calling works fine. Override via OLLAMA_DEFAULT_MODEL.
    return os.environ.get("OLLAMA_DEFAULT_MODEL", "gemma4:latest")


def _keep_alive() -> str:
    """How long Ollama keeps a model resident after a call. Keeping models hot
    avoids cold-load lag (~20s for a large model) and model-swap thrash when
    several agents run in a burst. Override via OLLAMA_KEEP_ALIVE (e.g. "60m",
    "-1" for forever, "0" to unload immediately)."""
    return os.environ.get("OLLAMA_KEEP_ALIVE", "5m")


def _parse_message(raw: dict[str, Any]) -> ChatMessage:
    """Parse Ollama's message format into our ChatMessage."""
    msg = raw.get("message", {})
    tool_calls: list[ToolCall] = []
    for tc in msg.get("tool_calls", []):
        fn = tc.get("function", {})
        # arguments may be a dict or a JSON string depending on Ollama version
        args = fn.get("arguments", {})
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                args = {}
        tool_calls.append(ToolCall(id=tc.get("id", ""), name=fn.get("name", ""), arguments=args))
    return ChatMessage(
        role=msg.get("role", "assistant"),
        content=msg.get("content", ""),
        tool_calls=tool_calls,
    )


class OllamaService:
    """Async client for the local Ollama server.

    Uses httpx.AsyncClient. One client instance per process is recommended;
    the FastAPI app holds a singleton on app.state.
    """

    def __init__(self, base_url: Optional[str] = None, model: Optional[str] = None):
        self.base_url = base_url or _default_base_url()
        self.model = model or _default_model()
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(base_url=self.base_url, timeout=httpx.Timeout(300.0))
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def health(self) -> bool:
        """True if Ollama has the model, OR the bundled llama-server is up."""
        try:
            client = await self._get_client()
            r = await client.get("/api/tags", timeout=5.0)
            r.raise_for_status()
            data = r.json()
            names = {m["name"] for m in data.get("models", [])}
            if self.model in names:
                return True
        except (httpx.HTTPError, httpx.RequestError, KeyError):
            pass
        # Bundled fallback: llama.cpp server (see services/local_llm.py)
        try:
            from backend.services import local_llm
            return local_llm.server_running()
        except Exception:
            return False

    async def warm_model(self) -> float:
        """Send a tiny prompt to force the model into memory. Returns seconds.

        The first call after ollama boot is slow (model load from disk). We
        don't want this latency to land on the user's first interaction, so
        we warm at server startup. Idempotent — calling twice is fine.
        """
        client = await self._get_client()
        payload = {
            "model": self.model,
            "prompt": "hi",
            "stream": False,
            "keep_alive": _keep_alive(),
        }
        r = await client.post("/api/generate", json=payload)
        r.raise_for_status()
        data = r.json()
        return data.get("total_duration", 0) / 1e9

    async def chat(
        self,
        messages: list[ChatMessage],
        tools: Optional[list[dict[str, Any]]] = None,
        think: bool = False,
        model: Optional[str] = None,
    ) -> ChatResponse:
        """One non-streaming chat turn. Returns the assistant message + telemetry.

        tools: list of {"type": "function", "function": {"name", "description", "parameters"}}
        think: enable extended thinking (Ollama returns a "thinking" field)
        model: override the service default for this call (per-agent routing).
        """
        client = await self._get_client()
        use_model = model or self.model
        payload: dict[str, Any] = {
            "model": use_model,
            "messages": [self._serialize_message(m) for m in messages],
            "stream": False,
            "keep_alive": _keep_alive(),
        }
        if tools:
            payload["tools"] = tools
        if think:
            payload["think"] = True
        try:
            r = await client.post("/api/chat", json=payload)
            r.raise_for_status()
            data = r.json()
        except (httpx.ConnectError, httpx.ConnectTimeout):
            # Ollama not installed/running → bundled llama-server fallback.
            data = await self._local_fallback_chat(messages, tools)
        except httpx.ReadTimeout:
            # Ollama is up and accepted the request but took too long to
            # respond. Do NOT silently switch models mid-request — that
            # would return an answer from a different model than the caller
            # asked for. Surface a clear, actionable error instead.
            raise RuntimeError(
                "the model took too long — try a shorter prompt or a smaller model"
            )
        return ChatResponse(
            message=_parse_message(data),
            model=data.get("model", use_model),
            total_duration_ns=data.get("total_duration", 0),
            prompt_eval_count=data.get("prompt_eval_count", 0),
            eval_count=data.get("eval_count", 0),
            done_reason=data.get("done_reason", "stop"),
        )

    async def _local_fallback_chat(
        self, messages: list[ChatMessage], tools: Optional[list[dict[str, Any]]]
    ) -> dict[str, Any]:
        """Chat via the bundled llama.cpp server (OpenAI format), translated
        back to the Ollama response shape. Raises the original-style
        ConnectError if the local server can't be brought up either."""
        from backend.services import local_llm
        import asyncio as _asyncio
        up = await _asyncio.to_thread(local_llm.ensure_running)
        if not up:
            raise httpx.ConnectError("no local AI: Ollama absent and bundled model not installed")
        payload: dict[str, Any] = {
            "model": "local",
            "messages": local_llm.to_openai_messages(messages),
            "stream": False,
        }
        if tools:
            payload["tools"] = tools  # already OpenAI-shaped
        async with httpx.AsyncClient(timeout=httpx.Timeout(300.0)) as c:
            r = await c.post(f"{local_llm.BASE_URL}/v1/chat/completions", json=payload)
            r.raise_for_status()
            return local_llm.from_openai_response(r.json())

    async def stream_chat(
        self,
        messages: list[ChatMessage],
        tools: Optional[list[dict[str, Any]]] = None,
        think: bool = False,
    ) -> AsyncIterator[dict[str, Any]]:
        """Streaming chat. Yields Ollama's raw NDJSON events (one dict per line).

        Use this for the agent runner's live UI updates. Each yielded dict is
        what Ollama sends in one NDJSON line.
        """
        client = await self._get_client()
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [self._serialize_message(m) for m in messages],
            "stream": True,
            "keep_alive": _keep_alive(),
        }
        if tools:
            payload["tools"] = tools
        if think:
            payload["think"] = True
        try:
            async with client.stream("POST", "/api/chat", json=payload) as r:
                r.raise_for_status()
                async for line in r.aiter_lines():
                    if line.strip():
                        yield json.loads(line)
        except (httpx.ConnectError, httpx.ConnectTimeout):
            # No fallback for streaming (bundled llama-server doesn't stream
            # in Ollama's NDJSON shape). Tell the SSE consumer plainly instead
            # of raising through the generator, which would break the stream.
            yield {
                "message": {"role": "assistant", "content": ""},
                "error": "no local AI: Ollama absent and bundled model not installed",
                "done": True,
            }

    @staticmethod
    def _serialize_message(m: ChatMessage) -> dict[str, Any]:
        out: dict[str, Any] = {"role": m.role, "content": m.content}
        if m.tool_calls:
            # Ollama expects `arguments` as an OBJECT, not a JSON string.
            # Double-encoding (json.dumps) is tolerated by some model templates
            # (gemma4) but rejected by stricter ones (qwen3 → 400 "Value looks
            # like object, but can't find closing '}'"). Send the dict directly.
            out["tool_calls"] = [
                {
                    "id": tc.id,
                    "function": {"name": tc.name, "arguments": tc.arguments},
                }
                for tc in m.tool_calls
            ]
        if m.role == "tool" and m.tool_call_id:
            out["tool_call_id"] = m.tool_call_id
        return out
