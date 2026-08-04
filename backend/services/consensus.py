"""Multi-model consensus — the PDF's `consensus` capability, native.

Ask the same question to a panel of *different model families* concurrently,
collect each one's stance, then combine them. Two modes:

- "synthesize" (default): a local model merges the stances into one
  recommendation — cheap, opinions never leave the machine for the summary.
- "council": full Multi-Model Council. After the stances come back, every
  panelist REVIEWS the full (anonymized) answer set and scores each answer;
  scores are tallied (self-votes excluded) and the best response wins.
  Costs ~2× the calls — use for the decisions that matter.

Model-agnostic and auth-aware: the panel is chosen from backends that are
actually ONLINE right now (so a dead Gemini free tier, or a logged-out CLI,
simply drops out instead of erroring the whole call).

Public interface:
    consensus(question, panel=None, synthesizer="ollama", mode="synthesize") -> dict
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import string

from backend.llm_hub import ChatMessage, get_backend, status_all

log = logging.getLogger(__name__)

# Preferred panel — three distinct model families for genuine diversity
# (Anthropic / OpenAI / Google). Filtered against what's online; topped up
# from the fallback pool so the council keeps three voices when one is out.
_PREFERRED_PANEL: tuple[str, ...] = ("claude", "codex", "gemini")
_FALLBACK_POOL: tuple[str, ...] = ("droid", "cursor")
_SYNTH_MODEL = os.environ.get("OLLAMA_DEFAULT_MODEL", "gemma4:latest")

# NOTE: instructions live in the USER message, not a system message — the
# CLI backends (claude/codex/gemini/droid/cursor) drop system messages when
# flattening the prompt for one-shot exec mode.
_STANCE_INSTRUCTIONS = (
    "You are one voice on an advisory panel. Answer the question below with a "
    "CLEAR stance in the first sentence (e.g. 'Yes, because…' / 'No, because…' / "
    "'It depends on…'), then 2–4 sentences of your strongest reasoning. Be "
    "decisive and concise. Do not hedge into a non-answer."
)


async def _ask_one(name: str, question: str) -> dict | None:
    """Query one backend for its stance. Returns None if it errors/offline."""
    try:
        backend = get_backend(name)
        # Ollama requires an explicit model; the CLI backends derive their own.
        model = _SYNTH_MODEL if name == "ollama" else ""
        result = await backend.chat(
            [ChatMessage("user", f"{_STANCE_INSTRUCTIONS}\n\nQuestion:\n{question}")],
            model=model,
        )
        text = (result.content or "").strip()
        if not text:
            return None
        return {"backend": name, "model": result.model, "stance": text,
                "elapsed_ms": result.elapsed_ms}
    except Exception as exc:  # noqa: BLE001
        log.warning("consensus: backend %s failed: %s", name, exc)
        return None


async def _online_panel(requested: list[str] | None) -> list[str]:
    """Resolve the panel to backends that are actually online right now."""
    statuses = await status_all()
    online = {n for n, r in statuses.items() if r.online}
    wanted = requested or list(_PREFERRED_PANEL)
    panel = [n for n in wanted if n in online]
    # Only top up an implicit (default) panel — an explicit request means
    # the caller wants exactly those voices, minus whoever is offline.
    if requested is None:
        for name in _FALLBACK_POOL:
            if len(panel) >= len(_PREFERRED_PANEL):
                break
            if name in online and name not in panel:
                panel.append(name)
    # If the panel is entirely offline, fall back to any online
    # non-local backend, then any online backend at all.
    if not panel:
        panel = [n for n in online if n not in ("hermes",)][:3] or list(online)[:3]
    return panel


# ── Council review (Level 3) ──────────────────────────────────────────
_JUDGE_INSTRUCTIONS = (
    "You are a strict, impartial judge on a review council. Below are a "
    "question and several candidate answers labeled with letters. Score EVERY "
    "answer from 1 (poor) to 10 (excellent) on correctness, completeness, and "
    "reasoning quality. Reply with ONLY a JSON object mapping each label to an "
    'integer score, e.g. {"A": 8, "B": 6}. No prose, no markdown fences.'
)


def _parse_scores(text: str, labels: list[str]) -> dict[str, float] | None:
    """Extract a {label: score} dict from a judge's reply, defensively."""
    m = re.search(r"\{[^{}]*\}", text or "", re.DOTALL)
    if not m:
        return None
    try:
        raw = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    scores: dict[str, float] = {}
    for k, v in raw.items():
        k = str(k).strip().upper()
        if k in labels and isinstance(v, (int, float)):
            scores[k] = max(1.0, min(10.0, float(v)))
    return scores or None


async def _judge_one(judge: str, question: str, block: str,
                     labels: list[str]) -> dict | None:
    """Ask one panelist to score the anonymized answer set."""
    try:
        backend = get_backend(judge)
        model = _SYNTH_MODEL if judge == "ollama" else ""
        prompt = (
            f"{_JUDGE_INSTRUCTIONS}\n\n"
            f"Question:\n{question}\n\n"
            f"Candidate answers:\n\n{block}\n\n"
            f"Score every answer ({', '.join(labels)}) — JSON only."
        )
        result = await backend.chat([ChatMessage("user", prompt)], model=model)
        scores = _parse_scores(result.content, labels)
        if not scores:
            log.warning("consensus: judge %s returned unparseable scores", judge)
            return None
        return {"judge": judge, "scores": scores}
    except Exception as exc:  # noqa: BLE001
        log.warning("consensus: judge %s failed: %s", judge, exc)
        return None


async def _council_review(question: str, stances: list[dict]) -> dict:
    """Cross-review round: every panelist scores the anonymized answers,
    self-votes are excluded from the tally, highest average wins."""
    labels = list(string.ascii_uppercase[: len(stances)])
    label_of = {s["backend"]: lab for lab, s in zip(labels, stances)}
    block = "\n\n".join(
        f"### Answer {lab}\n{s['stance']}" for lab, s in zip(labels, stances)
    )
    reviews = [r for r in await asyncio.gather(
        *(_judge_one(s["backend"], question, block, labels) for s in stances)
    ) if r]

    tally: dict[str, list[float]] = {lab: [] for lab in labels}
    for r in reviews:
        own = label_of.get(r["judge"])
        for lab, score in r["scores"].items():
            if lab != own:  # a judge never votes on its own answer
                tally[lab].append(score)
    averages = {
        lab: round(sum(v) / len(v), 2) for lab, v in tally.items() if v
    }
    return {"labels": label_of, "reviews": reviews, "averages": averages}


async def _synthesize(question: str, stances: list[dict], synthesizer: str) -> str:
    """Combine the panel's stances into one recommendation (local by default)."""
    if not stances:
        return "(no panelists were available to answer)"
    block = "\n\n".join(f"### {s['backend']} ({s['model']})\n{s['stance']}" for s in stances)
    prompt = (
        f"Question:\n{question}\n\n"
        f"The advisory panel gave these stances:\n\n{block}\n\n"
        "Synthesize them: state where they AGREE, where they DISAGREE, and give "
        "one clear final recommendation with the single most important reason. "
        "Be concise (≤6 sentences)."
    )
    try:
        backend = get_backend(synthesizer)
        model = _SYNTH_MODEL if synthesizer == "ollama" else ""
        result = await backend.chat(
            [ChatMessage("user", prompt)], model=model,
        )
        return (result.content or "").strip() or "(synthesis was empty)"
    except Exception as exc:  # noqa: BLE001
        log.warning("consensus: synthesis via %s failed: %s", synthesizer, exc)
        # Degrade gracefully — return the raw stances so the caller still has signal.
        return "Synthesis unavailable; raw stances:\n\n" + block


async def consensus(
    question: str,
    panel: list[str] | None = None,
    synthesizer: str = "ollama",
    mode: str = "synthesize",
) -> dict:
    """Get a multi-model second opinion on *question*.

    mode="synthesize" (default): fan out, then merge stances locally.
    mode="council": fan out, cross-review (each panelist scores the
    anonymized answers), pick the best response, then synthesize.

    Returns {question, mode, panel, stances, synthesis, best?, scores?, error}.
    Never raises — a fully-offline panel yields an empty stances list and an
    explanatory note; a failed review round degrades to synthesize.
    """
    question = (question or "").strip()
    if not question:
        return {"error": "question is required", "question": "", "stances": [], "synthesis": ""}
    if mode not in ("synthesize", "council"):
        return {"error": f"unknown mode: {mode}", "question": question,
                "stances": [], "synthesis": ""}

    members = await _online_panel(panel)
    if not members:
        return {"question": question, "mode": mode, "panel": [], "stances": [],
                "synthesis": "(no LLM backends are online)", "error": "no_backends"}

    results = await asyncio.gather(*(_ask_one(n, question) for n in members))
    stances = [r for r in results if r]

    out: dict = {
        "question": question,
        "mode": mode,
        "panel": members,
        "answered": [s["backend"] for s in stances],
        "stances": stances,
        "error": "",
    }

    # Council review — needs at least two answers to be meaningful.
    if mode == "council" and len(stances) >= 2:
        review = await _council_review(question, stances)
        if review["averages"]:
            best_label = max(review["averages"], key=review["averages"].get)
            best_backend = next(
                b for b, lab in review["labels"].items() if lab == best_label
            )
            best = next(s for s in stances if s["backend"] == best_backend)
            out["scores"] = {
                review["labels"][s["backend"]]: {
                    "backend": s["backend"],
                    "avg": review["averages"].get(review["labels"][s["backend"]]),
                }
                for s in stances
            }
            out["reviews"] = review["reviews"]
            out["best"] = {**best, "avg_score": review["averages"][best_label]}
        else:
            out["error"] = "council_review_failed"
            log.warning("consensus: council review produced no usable scores")

    out["synthesis"] = await _synthesize(question, stances, synthesizer)
    return out
