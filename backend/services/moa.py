"""Mixture of Agents ("Ministry of Experts") — advisor→aggregator, native.

Unlike `consensus` (peer voting: every panelist scores an anonymized answer
set, best response wins), MoA is a two-role pipeline:

- ADVISORS (reference models) each analyze the question in parallel and hand
  back private guidance — "here's the best approach, the pitfalls, what you
  might be missing." They do NOT produce the user-facing answer.
- The AGGREGATOR (the acting model) reads the original question plus every
  advisor's guidance and writes the single answer the user sees.

This mirrors the Together MoA paper and the Hermes `moa_loop.py` shape, but
routes through the existing hub backends (claude/codex/gemini/ollama) exactly
like `consensus.py` does — no raw provider keys held in this process, CLI auth
per backend. Advisors that error or go offline simply drop out; the aggregator
answers with whatever guidance survived (and can answer alone if all advisors
drop, degrading to a plain single-model call).

Public interface:
    moa(question, advisors=None, aggregator="claude", ...) -> dict
    moa_stream(question, ...) -> async iterator of SSE-shaped dicts
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import AsyncIterator

from backend.llm_hub import ChatMessage, get_backend, status_all

log = logging.getLogger(__name__)

# Default advisor panel — distinct families for genuine diversity, filtered
# against what's online. Kept off the aggregator so the acting model isn't
# also advising itself.
#
# Default lineup picks the LOCAL+ONLINE backend (ollama) for both advisors and
# aggregator by default — runs zero tokens, never leaves the machine, and is
# the only fully-online CLI family in the hub right now. Override per-request
# via the `advisors=[...]` / `aggregator="..."` fields, or set a different
# default in moa.py once the rest of the hub (claude, gemini) is back online.
_DEFAULT_ADVISORS: tuple[str, ...] = ("ollama", "droid")
_DEFAULT_AGGREGATOR = "ollama"
# Fallback advisors to top up an implicit panel when a preferred one is out.
# Note: keep the panel size cap at 1 (below) to avoid multi-CLI cold-start
# hangs. The hub's CLI backends (codex/droid/cursor/claude/gemini) each
# shell out to a binary that may take 10-30s on cold start; stacking two
# non-ollama voices behind the aggregator can blow the call past 3 minutes.
_FALLBACK_ADVISORS: tuple[str, ...] = ("cursor", "codex", "hermes")
# Cap the resolved panel to 1 voice by default. Multi-advisor panels are
# still allowed (pass advisors=[...] explicitly), but the implicit default
# is a single fast voice to keep wall time predictable. Users who want the
# full multi-model diversity can opt in per-request.
_DEFAULT_PANEL_CAP = 1
_OLLAMA_MODEL = os.environ.get("OLLAMA_DEFAULT_MODEL", "gemma4:latest")

# Per-advisor wall-clock cap. The CLI backends have their own internal
# timeouts (codex 180s, claude ~few seconds, etc.) but they can hang without
# raising if the binary is missing, the auth token is stale, or the network
# is wedged. Without this cap, one stuck advisor can block the whole MoA
# call past the FastAPI request timeout. 30s is generous for a healthy
# local model and tight enough that a hung CLI gets dropped in a reasonable
# window. The advisor's exception is swallowed (None → silently dropped),
# so the panel degrades naturally.
_ADVISOR_TIMEOUT_S = 30

# Per-advisor character cap when folding guidance into the aggregator prompt.
# An advisor that churns out 2000 words plus the question plus framing can push
# a small-context aggregator past its limit. Head+tail trim keeps the opening
# stance and the closing recommendation (where advisors put their conclusions)
# while dropping the sprawling middle. consensus.py avoids this by capping its
# stance instructions; MoA advisors are uncapped by design, so we trim here.
_ADVISOR_GUIDANCE_BUDGET = 4000

# Instructions live in the USER message, not a system message — the CLI
# backends (claude/codex/gemini/droid/cursor) drop system messages when
# flattening for one-shot exec. Same constraint consensus.py documents.
_ADVISOR_INSTRUCTIONS = (
    "You are a reference advisor in a Mixture of Agents process. You are NOT "
    "the acting agent and you do not produce the final answer — a separate "
    "aggregator model will. Give your most intelligent analysis of the "
    "question below: the best approach, concrete next steps, likely pitfalls, "
    "and anything the aggregator might miss or get wrong. Be direct and "
    "substantive; no preamble, no disclaimers. Your response is private "
    "guidance handed to the aggregator, not shown to the user."
)


def _expand_nous_alias(model_id: str) -> str | None:
    """Expand Nous '~*' aliases to real model names.
    
    Examples: ~anthropic/claude-fable-latest -> anthropic/claude-fable-5
              ~ollama/* -> stays as pattern (no expansion)
    
    For now, hardcode common free-tier models since we don't have live
    model list access in this helper. Return None if alias not known.
    """
    if not model_id.startswith("~"):
        return model_id  # Not an alias
    
    # Hardcoded mappings for common free/latest aliases
    alias_map = {
        "~anthropic/claude-fable-latest": "anthropic/claude-fable-5",
        "~tencent/hy3-latest": "tencent/hy3:free",
        "~x-ai/grok-latest": "x-ai/grok-4.5",
        "~ollama/*": None,  # Wildcard patterns stay as-is; caller expands
    }
    
    # Check for exact match or wildcard prefix
    if model_id in alias_map:
        return alias_map[model_id]
    
    # Wildcard match: ~* stays as pattern
    if model_id.startswith("~"):
        return model_id
    
    return model_id


def _backend_for_model(model_or_backend: str) -> str:
    """Resolve the backend from a model name or backend name.
    
    If the input is a backend name (ollama, claude, codex, etc.), return it.
    If it's a model ID (contains '/' or starts with '~'), return 'nous'.
    """
    if "/" in model_or_backend or model_or_backend.startswith("~"):
        return "nous"
    # It's either a backend name or an unsupported key — let the caller decide
    return model_or_backend


def _model_for(name: str) -> str:
    """Ollama needs an explicit model; CLI backends derive their own.
    
    If name is a full model ID (contains '/' or ':'), treat it as a Nous model
    and return it as-is for use with the nous backend. Otherwise, handle as a
    backend name (e.g., 'ollama', 'claude') which determines its own model.
    """
    if "/" in name or name.startswith("~"):
        # Full model ID: likely a Nous model like "tencent/hy3:free"
        return name
    return _OLLAMA_MODEL if name == "ollama" else ""


def _trim_guidance(text: str, budget: int = _ADVISOR_GUIDANCE_BUDGET) -> str:
    """Head+tail trim one advisor's guidance to keep the aggregator prompt
    inside context budgets. Advisors put their stance up front and their
    recommendation at the end, so we keep both halves and drop the middle."""
    if len(text) <= budget:
        return text
    half = budget // 2
    return f"{text[:half]}\n\n[... trimmed for length ...]\n\n{text[-half:]}"


async def _ask_advisor(name: str, question: str) -> dict | None:
    """Query one advisor for private guidance. None if it errors/offline/times out.

    Wraps the backend call in asyncio.wait_for with _ADVISOR_TIMEOUT_S so a
    wedged CLI binary (missing auth, hung subprocess, network stuck) can't
    block the whole MoA turn past the FastAPI request timeout. On timeout the
    advisor is silently dropped (returns None) so the rest of the panel
    proceeds.
    
    `name` can be either a backend name (e.g., 'ollama') or a full model ID
    (e.g., 'tencent/hy3:free'). The backend is resolved automatically.
    """
    try:
        backend_name = _backend_for_model(name)
        backend = get_backend(backend_name)
        model = _model_for(name)
        coro = backend.chat(
            [ChatMessage("user", f"{_ADVISOR_INSTRUCTIONS}\n\nQuestion:\n{question}")],
            model=model,
        )
        result = await asyncio.wait_for(coro, timeout=_ADVISOR_TIMEOUT_S)
        text = (result.content or "").strip()
        if not text:
            return None
        return {
            "backend": backend_name,
            "model": result.model,
            "guidance": text,
            "elapsed_ms": result.elapsed_ms,
        }
    except asyncio.TimeoutError:
        log.warning("moa: advisor %s timed out after %ds", name, _ADVISOR_TIMEOUT_S)
        return None
    except Exception as exc:  # noqa: BLE001
        log.warning("moa: advisor %s failed: %s", name, exc)
        return None


async def _online_advisors(requested: list[str] | None, aggregator: str) -> list[str]:
    """Resolve advisors to backends online right now, excluding the aggregator.

    Implicit (default) panels are capped to _DEFAULT_PANEL_CAP voices (1) so
    a default call stays in the 30-60s wall-time range — stacking two slow
    CLI backends (each with 10-30s cold start) can blow the call past the
    FastAPI request budget. Explicit panels (advisors=[...]) are NOT capped
    and the caller gets exactly what they asked for, minus offline voices.
    
    Advisors can be backend names (e.g., 'ollama') or full model IDs
    (e.g., 'tencent/hy3:free'). Model IDs are assumed to be online if their
    backend is online (nous models are live now).
    """
    statuses = await status_all()
    online_backends = {n for n, r in statuses.items() if r.online}
    wanted = requested if requested is not None else list(_DEFAULT_ADVISORS)
    
    # Filter: keep only those whose backend is online, and exclude the aggregator.
    panel = []
    for n in wanted:
        if n == aggregator:
            continue  # aggregator can't advise itself
        # Expand Nous aliases before checking backend
        expanded = _expand_nous_alias(n)
        if expanded is None:
            continue  # Alias not known
        backend_name = _backend_for_model(expanded)
        if backend_name in online_backends:
            panel.append(expanded)
    
    if requested is None:
        # Implicit (default) panel: hard cap to _DEFAULT_PANEL_CAP voices. The
        # initial preferred list is already filtered against online+aggregator,
        # so we may need to truncate it to honor the cap. The cap is checked
        # BEFORE the top-up loop too — otherwise the preferred list can already
        # exceed it (e.g. _DEFAULT_ADVISORS has 2 entries, both online, the
        # top-up loop bails on the first iteration, and the cap is never
        # enforced).
        panel = panel[:_DEFAULT_PANEL_CAP]
        # Then top up from the fallback pool, but only up to the cap.
        for name in _FALLBACK_ADVISORS:
            if len(panel) >= _DEFAULT_PANEL_CAP:
                break
            backend_name = _backend_for_model(name)
            if backend_name in online_backends and name not in panel and name != aggregator:
                panel.append(name)
    return panel


def _aggregator_prompt(question: str, advice: list[dict]) -> str:
    """Build the aggregator's user prompt from the question + advisor guidance.

    When no advice survived, the aggregator gets the bare question and acts as
    a plain single-model call — a graceful degrade, not an error.
    """
    if not advice:
        return question
    block = "\n\n".join(
        f"### Advisor {i} ({a['backend']}/{a['model']})\n{_trim_guidance(a['guidance'])}"
        for i, a in enumerate(advice, start=1)
    )
    return (
        f"Question:\n{question}\n\n"
        f"Several reference advisors analyzed this question. Their private "
        f"guidance to you:\n\n{block}\n\n"
        "Weigh their guidance where it's sound, discard it where it's wrong or "
        "irrelevant, and add anything they all missed. Then write the single "
        "best answer to the question for the user. Do not mention the advisors "
        "or that this was a multi-model process — just give the answer."
    )


async def _aggregate(question: str, advice: list[dict], aggregator: str) -> dict:
    """Run the aggregator over the question + surviving advisor guidance.
    
    `aggregator` can be either a backend name or a full model ID (including
    Nous aliases like ~anthropic/claude-fable-latest).
    """
    prompt = _aggregator_prompt(question, advice)
    expanded_agg = _expand_nous_alias(aggregator)
    if expanded_agg is None:
        raise ValueError(f"unknown aggregator: {aggregator}")
    backend_name = _backend_for_model(expanded_agg)
    backend = get_backend(backend_name)  # raises KeyError → caller maps to error
    model = _model_for(expanded_agg)
    result = await backend.chat(
        [ChatMessage("user", prompt)],
        model=model,
    )
    return {
        "content": (result.content or "").strip(),
        "model": result.model,
        "elapsed_ms": result.elapsed_ms,
        "tokens": result.tokens,
    }


async def moa(
    question: str,
    advisors: list[str] | None = None,
    aggregator: str = _DEFAULT_AGGREGATOR,
    include_advice: bool = False,
) -> dict:
    """Mixture-of-Agents answer: advisors analyze in parallel, aggregator acts.

    Returns {question, aggregator, advisors, answered, content, model,
    elapsed_ms, tokens, error}. Never raises — an unknown/offline aggregator
    yields an explanatory error; a fully-dropped advisor panel degrades to a
    plain single-model aggregator call.

    ``advice`` (each advisor's raw guidance) is PRIVATE by design — it's folded
    into the aggregator's prompt, not surfaced to the user. It appears in the
    result only when ``include_advice=True`` (debug/inspection). Without that,
    MoA would just be a noisier ``consensus`` where the user sees every
    advisor's raw output.
    """
    question = (question or "").strip()
    if not question:
        return {"error": "question is required", "question": "", "content": ""}

    # Validate the aggregator is a real backend before fanning out advisors —
    # no point paying for advice we can't aggregate.
    try:
        get_backend(aggregator)
    except KeyError:
        return {"error": f"unknown aggregator: {aggregator}", "question": question,
                "aggregator": aggregator, "content": ""}

    members = await _online_advisors(advisors, aggregator)
    # return_exceptions=True so one advisor's exception doesn't discard the
    # siblings' results. _ask_advisor already catches Exception and returns
    # None, so this only fires for BaseException subclasses (e.g.
    # asyncio.CancelledError on outer-task cancellation). We still drop those
    # results from `advice` below so a cancelled advisor never feeds the
    # aggregator — the surviving advisors carry on with their guidance.
    raw = await asyncio.gather(
        *(_ask_advisor(n, question) for n in members),
        return_exceptions=True,
    )
    advice: list[dict] = []
    for n, r in zip(members, raw):
        if isinstance(r, BaseException):
            log.warning("moa: advisor %s raised %s: %s", n,
                        type(r).__name__, r)
            continue
        if r is not None:
            advice.append(r)

    out: dict = {
        "question": question,
        "aggregator": aggregator,
        "advisors": members,
        "answered": [a["backend"] for a in advice],
        "error": "",
    }
    if include_advice:
        out["advice"] = advice

    try:
        agg = await _aggregate(question, advice, aggregator)
    except Exception as exc:  # noqa: BLE001
        log.warning("moa: aggregator %s failed: %s", aggregator, exc)
        out["error"] = f"aggregator_failed: {type(exc).__name__}"
        out["content"] = ""
        return out

    out.update(
        content=agg["content"],
        model=agg["model"],
        elapsed_ms=agg["elapsed_ms"],
        tokens=agg["tokens"],
    )
    if not agg["content"]:
        out["error"] = "empty_aggregation"
    return out


async def moa_stream(
    question: str,
    advisors: list[str] | None = None,
    aggregator: str = _DEFAULT_AGGREGATOR,
    include_advice: bool = False,
) -> AsyncIterator[dict]:
    """Streaming variant — emits progress events so the UI can show the panel
    filling in before the final answer lands.

    Event shapes (each yielded as a dict; the endpoint SSE-encodes them):
      {"phase": "advisors", "panel": [...]}         # panel resolved
      {"phase": "advisor_done", "backend": "...", "ok": bool}
      {"phase": "aggregating", "aggregator": "..."}
      {"phase": "done", **full moa() result}        # terminal
      {"phase": "error", "error": "..."}             # terminal

    Advisor calls are NOT token-streamed (the CLI backends are one-shot); this
    streams *phase* progress, then the aggregator's answer in one final event.
    Only the aggregator answer needs token streaming, and that's a follow-up
    once an OpenRouterBackend with real SSE exists.
    """
    question = (question or "").strip()
    if not question:
        yield {"phase": "error", "error": "question is required"}
        return
    try:
        get_backend(aggregator)
    except KeyError:
        yield {"phase": "error", "error": f"unknown aggregator: {aggregator}"}
        return

    members = await _online_advisors(advisors, aggregator)
    yield {"phase": "advisors", "panel": members}

    # Fan out advisors; emit a progress event as each finishes. asyncio's
    # as_completed() yields wrapper Futures, NOT the original Tasks, so a dict
    # keyed by Task can't recover the advisor name from the completed item.
    # We wrap each call to carry its own name through the await instead.
    async def _named(name: str) -> tuple[str, dict | None]:
        return (name, await _ask_advisor(name, question))

    advice: list[dict] = []
    for coro in asyncio.as_completed([_named(n) for n in members]):
        name, result = await coro
        if result:
            advice.append(result)
        yield {"phase": "advisor_done", "backend": name, "ok": result is not None}

    yield {"phase": "aggregating", "aggregator": aggregator}
    try:
        agg = await _aggregate(question, advice, aggregator)
    except Exception as exc:  # noqa: BLE001
        log.warning("moa_stream: aggregator %s failed: %s", aggregator, exc)
        yield {"phase": "error", "error": f"aggregator_failed: {type(exc).__name__}"}
        return

    done: dict = {
        "phase": "done",
        "question": question,
        "aggregator": aggregator,
        "advisors": members,
        "answered": [a["backend"] for a in advice],
        "content": agg["content"],
        "model": agg["model"],
        "elapsed_ms": agg["elapsed_ms"],
        "tokens": agg["tokens"],
        "error": "" if agg["content"] else "empty_aggregation",
    }
    if include_advice:
        done["advice"] = advice
    yield done
