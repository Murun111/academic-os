"""Eval harness — blueprint §2.3 / roadmap B2.

The domain-general way to *prove* a change helped. An "eval" is a fixed set of
cases, each scored by either a deterministic assertion or a local-LLM rubric
judge. A runner scores the set, persists a dated run under ``data/evals/``, and
compares against the last baseline — a regression (a case that passed before and
fails now) is a non-zero exit, so it is usable as a CI/ship gate.

A "subject" (roadmap §3) is just: a *target* (the thing under test) + cases +
scorers. B2 ships the machinery and a builtin ``echo`` target; Phase C registers
the translator target against this same harness.

Local-first: the rubric judge reuses the Ollama backend (same pattern as the
critic). When no LLM is reachable, a rubric case scores ``skipped`` — never a
false ``pass`` — so an offline run cannot manufacture green results.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

import yaml

from backend.llm_hub import ChatMessage, get_backend
from backend.vault import agentic_os_dir

_RUBRIC_MODEL = os.environ.get("OLLAMA_DEFAULT_MODEL", "gemma4:latest")

# --- Outcome constants ------------------------------------------------------
PASS = "pass"
FAIL = "fail"
SKIPPED = "skipped"  # case could not be scored (e.g. rubric judge offline)


# --- Target registry --------------------------------------------------------
# A target maps a case input -> an output string. Targets may be sync or async.
# Phase C registers the translator here; B2 ships only the builtin echo target.

TargetFn = Callable[[Any], Any]
_TARGETS: dict[str, TargetFn] = {}


def register_target(name: str, fn: TargetFn) -> None:
    _TARGETS[name] = fn


def _echo(value: Any) -> Any:
    """Identity target — lets the harness self-test deterministically with no LLM."""
    return value


register_target("builtin:echo", _echo)


async def _run_target(name: str, value: Any) -> str:
    fn = _TARGETS.get(name)
    if fn is None:
        raise KeyError(f"unknown eval target: {name!r}")
    out = fn(value)
    if hasattr(out, "__await__"):
        out = await out
    return out if isinstance(out, str) else json.dumps(out, default=str)


# --- Case + result shapes ---------------------------------------------------
@dataclass
class EvalCase:
    id: str
    kind: str                       # "deterministic" | "rubric"
    target: str = "builtin:echo"
    input: Any = None
    expected: Any = None            # deterministic: the expected value
    expected_any: Any = None        # chrf match: list of accepted refs — score = best chrF
    match: str = "equals"           # deterministic: equals | contains | regex | chrf
    min_chrf: float = 0.4           # chrf match: pass when chrF(output, expected) >= this
    rubric: str = ""                # rubric: the judging instruction


@dataclass
class EvalResult:
    id: str
    kind: str
    outcome: str                    # PASS | FAIL | SKIPPED
    score: float = 0.0
    reason: str = ""
    output: str = ""

    @property
    def passed(self) -> bool:
        return self.outcome == PASS

    def to_dict(self) -> dict:
        return {
            "id": self.id, "kind": self.kind, "outcome": self.outcome,
            "score": self.score, "reason": self.reason, "output": self.output[:200],
        }


def load_cases(path: Path) -> list[EvalCase]:
    """Load a YAML (or JSON — YAML is a superset) list of cases into EvalCase[]."""
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or []
    if isinstance(raw, dict):  # tolerate {cases: [...]} wrapper
        raw = raw.get("cases", [])
    cases: list[EvalCase] = []
    for item in raw:
        if not isinstance(item, dict):
            continue  # skip stray scalars / malformed list entries
        known = {f: item[f] for f in EvalCase.__dataclass_fields__ if f in item}
        cases.append(EvalCase(**known))
    return cases


# --- Scorers ----------------------------------------------------------------
def score_deterministic(case: EvalCase, output: str) -> EvalResult:
    exp = case.expected
    match = (case.match or "equals").lower()
    if match == "equals":
        ok = output == (exp if isinstance(exp, str) else json.dumps(exp, default=str))
    elif match == "contains":
        ok = str(exp) in output
    elif match == "regex":
        try:
            ok = re.search(str(exp), output) is not None
        except re.error as exc:
            return EvalResult(case.id, case.kind, FAIL, 0.0,
                              f"bad regex {exp!r}: {exc}", output)
    else:
        return EvalResult(case.id, case.kind, FAIL, 0.0,
                          f"unknown match type: {match}", output)
    return EvalResult(case.id, case.kind, PASS if ok else FAIL,
                      1.0 if ok else 0.0,
                      "matched" if ok else f"expected {match} {exp!r}", output)


# A judge takes (rubric, input, output) -> dict {pass: bool, score: float, reason}.
JudgeFn = Callable[[str, Any, str], Awaitable[dict]]


async def _ollama_judge(rubric: str, input_value: Any, output: str) -> dict:
    """Default rubric judge — a local Ollama call, same backend as the critic."""
    system = (
        "You are a strict evaluator. Given a RUBRIC, the INPUT, and the OUTPUT, "
        'decide if the output satisfies the rubric. Return ONLY JSON: '
        '{"pass": true|false, "score": 0.0-1.0, "reason": "<short>"}.'
    )
    user = f"RUBRIC:\n{rubric}\n\nINPUT:\n{input_value}\n\nOUTPUT:\n{output[:2000]}"
    backend = get_backend("ollama")
    result = await backend.chat(
        [ChatMessage("system", system), ChatMessage("user", user)],
        model=_RUBRIC_MODEL,
    )
    m = re.search(r"\{.*\}", result.content or "", re.DOTALL)
    try:
        data = json.loads(m.group(0)) if m else {}
    except (ValueError, json.JSONDecodeError):
        data = {}
    return data if isinstance(data, dict) else {}


async def score_rubric(case: EvalCase, output: str,
                       judge: Optional[JudgeFn] = None) -> EvalResult:
    """Score a rubric case. Offline/judge-error → SKIPPED (never a false PASS)."""
    judge = judge or _ollama_judge
    try:
        data = await judge(case.rubric, case.input, output)
    except Exception as exc:  # noqa: BLE001 — judge unreachable / errored
        return EvalResult(case.id, case.kind, SKIPPED, 0.0,
                          f"rubric judge unavailable: {type(exc).__name__}", output)
    if not data:
        return EvalResult(case.id, case.kind, SKIPPED, 0.0,
                          "rubric judge returned no verdict", output)
    passed = bool(data.get("pass", False))
    try:
        score = float(data.get("score", 1.0 if passed else 0.0))
    except (TypeError, ValueError):
        score = 1.0 if passed else 0.0  # a non-numeric score is not a crash
    return EvalResult(case.id, case.kind, PASS if passed else FAIL,
                      score, str(data.get("reason", ""))[:300], output)


# --- Runner -----------------------------------------------------------------
async def run_case(case: EvalCase, judge: Optional[JudgeFn] = None) -> EvalResult:
    try:
        output = await _run_target(case.target, case.input)
    except Exception as exc:  # noqa: BLE001 — a broken target is a FAIL, not a crash
        return EvalResult(case.id, case.kind, FAIL, 0.0,
                          f"target error: {type(exc).__name__}: {exc}")
    if case.kind == "rubric":
        return await score_rubric(case, output, judge=judge)
    return score_deterministic(case, output)


async def run_cases(cases: list[EvalCase],
                    judge: Optional[JudgeFn] = None) -> list[EvalResult]:
    return [await run_case(c, judge=judge) for c in cases]


def summarize(results: list[EvalResult]) -> dict:
    return {
        "total": len(results),
        "passed": sum(r.outcome == PASS for r in results),
        "failed": sum(r.outcome == FAIL for r in results),
        "skipped": sum(r.outcome == SKIPPED for r in results),
    }


# --- Persistence + baseline -------------------------------------------------
class EvalStore:
    """Dated eval runs under ``data/evals/``; newest file is the baseline."""

    def __init__(self, base_dir: Optional[Path] = None):
        if base_dir is None:
            base_dir = agentic_os_dir() / "data" / "evals"
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def save(self, results: list[EvalResult], stamp: Optional[str] = None) -> Path:
        stamp = stamp or datetime.now().strftime("%Y%m%dT%H%M%S")
        path = self.base_dir / f"{stamp}.json"
        payload = {
            "stamp": stamp,
            "summary": summarize(results),
            "results": [r.to_dict() for r in results],
        }
        path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        return path

    def _runs(self) -> list[Path]:
        return sorted(self.base_dir.glob("*.json"))

    def baseline(self, before: Optional[Path] = None) -> Optional[dict]:
        """Latest run on disk (optionally the latest *before* a given file)."""
        runs = self._runs()
        if before is not None:
            runs = [p for p in runs if p.name < before.name]
        if not runs:
            return None
        try:
            return json.loads(runs[-1].read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None


def regressions(current: list[EvalResult], baseline: Optional[dict]) -> list[str]:
    """Case ids that PASSED in *baseline* but no longer pass now.

    SKIPPED is never counted as a regression (the judge being offline is not a
    quality regression). No baseline → no regressions (first run establishes it).
    """
    if not baseline:
        return []
    base_pass = {r["id"] for r in baseline.get("results", []) if r.get("outcome") == PASS}
    now = {r.id: r for r in current}
    out = []
    for cid in base_pass:
        r = now.get(cid)
        if r is not None and r.outcome == FAIL:
            out.append(cid)
    return sorted(out)


def missing_passes(current: list[EvalResult], baseline: Optional[dict]) -> list[str]:
    """Case ids that PASSED in *baseline* but are absent from the current run.

    Deleting a previously-passing case would otherwise silently shrink the gate
    (it is not a FAIL, so `regressions` won't catch it). Surfaced separately so a
    dropped case is visible, without forcing it to fail the run."""
    if not baseline:
        return []
    base_pass = {r["id"] for r in baseline.get("results", []) if r.get("outcome") == PASS}
    now_ids = {r.id for r in current}
    return sorted(base_pass - now_ids)


async def run_evals(cases_path: Path, store: Optional[EvalStore] = None,
                    judge: Optional[JudgeFn] = None) -> dict:
    """Load → run → persist → compare to baseline. Returns a report dict with
    ``exit_code`` (0 ok, 1 regression) for the CLI to consume."""
    store = store or EvalStore()
    cases = load_cases(cases_path)
    results = await run_cases(cases, judge=judge)
    # Save first, then read the baseline EXCLUDING the run we just wrote. This
    # makes the "never compare against yourself" invariant explicit and
    # refactor-proof (instead of relying on call ordering).
    saved = store.save(results)
    baseline = store.baseline(before=saved)
    regressed = regressions(results, baseline)
    missing = missing_passes(results, baseline)
    return {
        "summary": summarize(results),
        "regressions": regressed,
        "missing": missing,
        "saved": str(saved),
        "exit_code": 1 if regressed else 0,
        "results": [r.to_dict() for r in results],
    }
