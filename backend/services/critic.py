"""Critic / verifier — verify agent output BEFORE it is committed (blueprint §2.2).

A cheap local-model reviewer that runs between an agent's tool-loop and the
memory write-back. It answers: did the output actually meet the goal, is it
well-formed, and does it contradict known memory? — and returns a verdict the
runner acts on (pass / retry-once / escalate).

Design stance: this is an ENHANCEMENT, not a gate. It **fails open** — any error,
timeout, or unparseable response yields `pass`, so a flaky critic never blocks a
run or makes the system worse than having no critic. Disable entirely with
AGENT_CRITIC=0.

Public interface:
    verify(goal, output, agent="") -> CriticVerdict
"""
from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass

from backend.llm_hub import ChatMessage, get_backend

log = logging.getLogger(__name__)

_MODEL = os.environ.get("OLLAMA_DEFAULT_MODEL", "gemma4:latest")
_VALID = ("pass", "retry", "escalate")

_SYSTEM = (
    "You are a strict but fair reviewer. Judge whether an agent's OUTPUT satisfies "
    "its GOAL. Consider: did it actually address the goal? is it well-formed and "
    "non-empty? does it contradict the KNOWN FACTS provided?\n\n"
    'Return ONLY JSON: {"verdict": "pass"|"retry"|"escalate", '
    '"reason": "<short>", "contradicts_memory": true|false}.\n'
    "- pass: the output is good enough.\n"
    "- retry: fixable by trying again (incomplete, malformed, or ignored the goal).\n"
    "- escalate: contradicts known facts, or makes a risky/irreversible claim a "
    "human should check.\n"
    "No prose, no markdown fences — only the JSON object."
)


@dataclass
class CriticVerdict:
    verdict: str            # one of _VALID
    reason: str = ""
    contradicts_memory: bool = False

    def to_dict(self) -> dict:
        return {"verdict": self.verdict, "reason": self.reason,
                "contradicts_memory": self.contradicts_memory}


def _recall_facts(goal: str) -> str:
    """Best-effort: pull a few relevant memory items to check contradictions."""
    try:
        from backend.services.memory_index import search
        items = search(goal, k=5)
        return "\n".join(f"- {it.subject}: {it.body}" for it in items)[:1500]
    except Exception:  # noqa: BLE001
        return ""


def _parse_json(raw: str) -> dict:
    text = re.sub(r"```(?:json)?\s*", "", raw or "", flags=re.IGNORECASE)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return {}
    try:
        obj = json.loads(text[start:end + 1])
        return obj if isinstance(obj, dict) else {}
    except json.JSONDecodeError:
        return {}


async def verify(goal: str, output: str, agent: str = "") -> CriticVerdict:
    """Review *output* against *goal*. Fails open to 'pass' on any error."""
    if os.environ.get("AGENT_CRITIC", "1") == "0":
        return CriticVerdict("pass", "critic disabled")
    output = (output or "").strip()
    if not output:
        return CriticVerdict("retry", "empty output")

    facts = _recall_facts(goal)
    user = (
        f"GOAL:\n{goal or '(unspecified)'}\n\n"
        f"OUTPUT:\n{output[:2000]}\n\n"
        f"KNOWN FACTS:\n{facts or '(none)'}"
    )
    try:
        backend = get_backend("ollama")
        result = await backend.chat(
            [ChatMessage("system", _SYSTEM), ChatMessage("user", user)],
            model=_MODEL,
        )
        data = _parse_json(result.content)
    except Exception as exc:  # noqa: BLE001
        log.warning("critic.verify failed (fail-open): %s: %s", type(exc).__name__, exc)
        return CriticVerdict("pass", f"critic error (fail-open): {type(exc).__name__}")

    verdict = str(data.get("verdict", "pass")).strip().lower()
    if verdict not in _VALID:
        verdict = "pass"
    return CriticVerdict(
        verdict=verdict,
        reason=str(data.get("reason", ""))[:300],
        contradicts_memory=bool(data.get("contradicts_memory", False)),
    )
