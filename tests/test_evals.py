"""Tests for the eval harness (roadmap B2).

Covers: case loading, deterministic scorers (equals/contains/regex + fail),
rubric scorer (mocked judge pass/fail + offline→skipped), target errors,
store save/baseline roundtrip, and regression→exit-code semantics.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from backend.services.evals import (
    EvalCase,
    EvalResult,
    EvalStore,
    PASS,
    FAIL,
    SKIPPED,
    load_cases,
    missing_passes,
    regressions,
    run_case,
    run_evals,
    score_deterministic,
    summarize,
)

CASES_YAML = Path(__file__).resolve().parent / "eval" / "cases.yaml"


def _run(coro):
    return asyncio.run(coro)


# --- loading ----------------------------------------------------------------

def test_load_cases_from_shipped_yaml():
    cases = load_cases(CASES_YAML)
    ids = {c.id for c in cases}
    assert {"echo-exact", "echo-contains", "echo-regex", "echo-rubric-smoke"} <= ids
    assert any(c.kind == "rubric" for c in cases)
    assert any(c.kind == "deterministic" for c in cases)


def test_load_cases_tolerates_wrapper_and_unknown_keys(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text(
        "cases:\n"
        "  - id: a\n    kind: deterministic\n    input: x\n    expected: x\n"
        "    bogus_field: ignored\n",
        encoding="utf-8",
    )
    cases = load_cases(p)
    assert len(cases) == 1 and cases[0].id == "a"


# --- deterministic scorer ---------------------------------------------------

@pytest.mark.parametrize("match,expected,output,ok", [
    ("equals", "hi", "hi", True),
    ("equals", "hi", "ho", False),
    ("contains", "ll", "hello", True),
    ("contains", "zz", "hello", False),
    ("regex", r"#\d{4}", "order #4271", True),
    ("regex", r"#\d{4}", "order #42", False),
])
def test_deterministic_match_types(match, expected, output, ok):
    case = EvalCase(id="t", kind="deterministic", match=match, expected=expected)
    res = score_deterministic(case, output)
    assert res.passed is ok
    assert res.score == (1.0 if ok else 0.0)


def test_deterministic_unknown_match_is_fail():
    case = EvalCase(id="t", kind="deterministic", match="fuzzy", expected="x")
    assert score_deterministic(case, "x").outcome == FAIL


# --- rubric scorer (mocked judge) -------------------------------------------

def test_rubric_pass_with_mock_judge():
    async def judge(rubric, inp, out):
        return {"pass": True, "score": 0.9, "reason": "ok"}
    case = EvalCase(id="r", kind="rubric", target="builtin:echo", input="x", rubric="...")
    res = _run(run_case(case, judge=judge))
    assert res.outcome == PASS and res.score == 0.9


def test_rubric_fail_with_mock_judge():
    async def judge(rubric, inp, out):
        return {"pass": False, "reason": "nope"}
    case = EvalCase(id="r", kind="rubric", input="x", rubric="...")
    assert _run(run_case(case, judge=judge)).outcome == FAIL


def test_rubric_offline_is_skipped_not_pass():
    async def judge(rubric, inp, out):
        raise ConnectionError("ollama down")
    case = EvalCase(id="r", kind="rubric", input="x", rubric="...")
    res = _run(run_case(case, judge=judge))
    assert res.outcome == SKIPPED  # crucial: offline must NOT be a false pass


def test_rubric_empty_verdict_is_skipped():
    async def judge(rubric, inp, out):
        return {}
    case = EvalCase(id="r", kind="rubric", input="x", rubric="...")
    assert _run(run_case(case, judge=judge)).outcome == SKIPPED


# --- target errors ----------------------------------------------------------

def test_unknown_target_is_fail_not_crash():
    case = EvalCase(id="t", kind="deterministic", target="builtin:nope", expected="x")
    assert _run(run_case(case)).outcome == FAIL


# --- store + baseline + regressions -----------------------------------------

def test_store_save_and_baseline_roundtrip(tmp_path):
    store = EvalStore(base_dir=tmp_path / "evals")
    store.save([EvalResult("a", "deterministic", PASS, 1.0)], stamp="20260630T100000")
    base = store.baseline()
    assert base["summary"]["passed"] == 1
    assert base["results"][0]["id"] == "a"


def test_no_baseline_means_no_regression():
    current = [EvalResult("a", "deterministic", FAIL, 0.0)]
    assert regressions(current, None) == []


def test_regression_detected_when_pass_becomes_fail():
    baseline = {"results": [{"id": "a", "outcome": PASS}, {"id": "b", "outcome": PASS}]}
    current = [EvalResult("a", "deterministic", FAIL, 0.0),
               EvalResult("b", "deterministic", PASS, 1.0)]
    assert regressions(current, baseline) == ["a"]


def test_skipped_now_is_not_a_regression():
    baseline = {"results": [{"id": "a", "outcome": PASS}]}
    current = [EvalResult("a", "rubric", SKIPPED, 0.0)]
    assert regressions(current, baseline) == []  # offline judge != quality regression


def test_deleted_passing_case_is_surfaced_as_missing_not_regression():
    baseline = {"results": [{"id": "a", "outcome": PASS}, {"id": "b", "outcome": PASS}]}
    current = [EvalResult("a", "deterministic", PASS, 1.0)]  # 'b' was dropped
    assert regressions(current, baseline) == []     # not a FAIL → not a regression
    assert missing_passes(current, baseline) == ["b"]  # but surfaced as dropped


def test_rubric_non_numeric_score_does_not_crash():
    async def judge(rubric, inp, out):
        return {"pass": True, "score": "high"}  # malformed score
    case = EvalCase(id="r", kind="rubric", input="x", rubric="...")
    res = _run(run_case(case, judge=judge))
    assert res.outcome == PASS and res.score == 1.0  # degrades, not crashes


def test_bad_regex_in_case_is_fail_not_crash():
    case = EvalCase(id="t", kind="deterministic", match="regex", expected="(a+")  # unbalanced
    res = score_deterministic(case, "aaa")
    assert res.outcome == FAIL and "bad regex" in res.reason


def test_load_cases_skips_non_dict_items(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text("- oops\n- id: a\n  kind: deterministic\n  expected: x\n", encoding="utf-8")
    cases = load_cases(p)
    assert [c.id for c in cases] == ["a"]


def test_summarize_counts():
    res = [EvalResult("a", "deterministic", PASS), EvalResult("b", "rubric", SKIPPED),
           EvalResult("c", "deterministic", FAIL)]
    s = summarize(res)
    assert (s["passed"], s["failed"], s["skipped"], s["total"]) == (1, 1, 1, 3)


# --- end-to-end run_evals (offline: deterministic pass, rubric skipped) ------

def test_run_evals_end_to_end_offline(tmp_path):
    store = EvalStore(base_dir=tmp_path / "evals")

    async def offline_judge(rubric, inp, out):
        raise ConnectionError("offline")

    report = _run(run_evals(CASES_YAML, store=store, judge=offline_judge))
    assert report["exit_code"] == 0           # first run, no baseline → no regression
    assert report["summary"]["passed"] >= 3   # the 3 deterministic echo cases
    assert report["summary"]["skipped"] >= 1  # the rubric case, offline
    assert Path(report["saved"]).exists()


def test_run_evals_flags_regression_against_baseline(tmp_path):
    store = EvalStore(base_dir=tmp_path / "evals")
    # Seed a baseline where a deterministic case passed.
    store.save([EvalResult("echo-exact", "deterministic", PASS, 1.0)],
               stamp="20260101T000000")

    # Now run a case set where echo-exact is rigged to FAIL (wrong expected).
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        "- id: echo-exact\n  kind: deterministic\n  target: builtin:echo\n"
        "  input: hello\n  match: equals\n  expected: GOODBYE\n",
        encoding="utf-8",
    )
    report = _run(run_evals(bad, store=store))
    assert report["regressions"] == ["echo-exact"]
    assert report["exit_code"] == 1
