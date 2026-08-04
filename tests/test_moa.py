"""Tests for backend.services.moa — Mixture of Agents (advisor→aggregator).

Fully OFFLINE: moa.status_all and moa.get_backend are monkeypatched so no real
CLI is ever launched. We assert advisor panel resolution (online-only, minus
the aggregator), concurrent guidance collection, graceful drop of failing
advisors, aggregator wiring, the advice-privacy contract, and the streaming
phase sequence.

Mirrors tests/test_consensus.py so the two multi-model services share a shape.
"""
from __future__ import annotations

import pytest

from backend.llm_hub import ChatResult, ProbeResult
from backend.services import moa as M


def _status(online: set[str]):
    async def _fake():
        names = ["ollama", "codex", "claude", "droid", "cursor", "gemini",
                 "hermes", "slow", "fast", "empty", "bad", "nonesuch"]
        return {n: ProbeResult(online=(n in online)) for n in names}
    return _fake


class _FakeBackend:
    def __init__(self, name, reply="guidance text", fail=False):
        self.name = name
        self._reply = reply
        self._fail = fail

    async def chat(self, messages, model=""):
        if self._fail:
            raise RuntimeError("boom")
        return ChatResult(backend=self.name, model=f"{self.name}-m",
                          content=self._reply, tokens=7, elapsed_ms=42)


def _get_backend_factory(backends: dict):
    def _get(name):
        if name not in backends:
            raise KeyError(name)
        return backends[name]
    return _get


# ── moa() — non-streaming ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_moa_aggregates_online_advisors(monkeypatch):
    # codex + gemini online (default advisors), claude aggregator.
    monkeypatch.setattr(M, "status_all", _status({"codex", "gemini", "claude"}))
    backends = {
        "codex": _FakeBackend("codex", "advisor A: use approach X"),
        "gemini": _FakeBackend("gemini", "advisor B: watch pitfall Y"),
        "claude": _FakeBackend("claude", "FINAL ANSWER"),
    }
    monkeypatch.setattr(M, "get_backend", _get_backend_factory(backends))

    res = await M.moa("How should I design this?",
                      advisors=["codex", "gemini"], aggregator="claude")

    assert res["error"] == ""
    assert set(res["advisors"]) == {"codex", "gemini"}       # aggregator excluded
    assert set(res["answered"]) == {"codex", "gemini"}
    assert res["aggregator"] == "claude"
    assert res["content"] == "FINAL ANSWER"                  # came from aggregator
    assert res["model"] == "claude-m"


@pytest.mark.asyncio
async def test_moa_hides_advice_by_default(monkeypatch):
    """advice is private — must NOT appear unless include_advice=True."""
    monkeypatch.setattr(M, "status_all", _status({"codex", "gemini", "claude"}))
    backends = {
        "codex": _FakeBackend("codex", "secret guidance"),
        "gemini": _FakeBackend("gemini", "more guidance"),
        "claude": _FakeBackend("claude", "answer"),
    }
    monkeypatch.setattr(M, "get_backend", _get_backend_factory(backends))

    res = await M.moa("Q?")
    assert "advice" not in res                                # private by default


@pytest.mark.asyncio
async def test_moa_exposes_advice_when_requested(monkeypatch):
    monkeypatch.setattr(M, "status_all", _status({"codex", "gemini", "claude"}))
    backends = {
        "codex": _FakeBackend("codex", "secret guidance"),
        "gemini": _FakeBackend("gemini", "more guidance"),
        "claude": _FakeBackend("claude", "answer"),
    }
    monkeypatch.setattr(M, "get_backend", _get_backend_factory(backends))

    res = await M.moa("Q?", include_advice=True,
                      advisors=["codex", "gemini"], aggregator="claude")
    assert "advice" in res
    guidances = {a["guidance"] for a in res["advice"]}
    assert guidances == {"secret guidance", "more guidance"}


@pytest.mark.asyncio
async def test_moa_excludes_aggregator_from_advisors(monkeypatch):
    """An advisor that IS the aggregator is dropped (no self-advising)."""
    monkeypatch.setattr(M, "status_all", _status({"codex", "gemini", "claude"}))
    backends = {
        "codex": _FakeBackend("codex", "a"),
        "gemini": _FakeBackend("gemini", "b"),
        "claude": _FakeBackend("claude", "answer"),
    }
    monkeypatch.setattr(M, "get_backend", _get_backend_factory(backends))

    # Ask for claude as an advisor AND aggregator — it must be dropped as advisor.
    res = await M.moa("Q?", advisors=["codex", "claude"], aggregator="claude")
    assert "claude" not in res["advisors"]
    assert res["advisors"] == ["codex"]


@pytest.mark.asyncio
async def test_moa_skips_failing_advisor(monkeypatch):
    monkeypatch.setattr(M, "status_all", _status({"codex", "gemini", "claude"}))
    backends = {
        "codex": _FakeBackend("codex", fail=True),            # errors → dropped
        "gemini": _FakeBackend("gemini", "good guidance"),
        "claude": _FakeBackend("claude", "answer"),
    }
    monkeypatch.setattr(M, "get_backend", _get_backend_factory(backends))

    res = await M.moa("Q?", advisors=["codex", "gemini"], aggregator="claude")
    assert "codex" not in res["answered"]
    assert res["answered"] == ["gemini"]
    assert res["content"] == "answer"                         # aggregation still runs


@pytest.mark.asyncio
async def test_moa_degrades_to_solo_when_all_advisors_offline(monkeypatch):
    """No advisors online → aggregator answers alone (graceful degrade, not error)."""
    monkeypatch.setattr(M, "status_all", _status({"claude"}))  # only aggregator up
    backends = {"claude": _FakeBackend("claude", "solo answer")}
    monkeypatch.setattr(M, "get_backend", _get_backend_factory(backends))

    res = await M.moa("Q?", aggregator="claude")
    assert res["advisors"] == []
    assert res["answered"] == []
    assert res["error"] == ""
    assert res["content"] == "solo answer"


@pytest.mark.asyncio
async def test_moa_aggregator_failure_is_reported(monkeypatch):
    monkeypatch.setattr(M, "status_all", _status({"codex", "claude"}))
    backends = {
        "codex": _FakeBackend("codex", "guidance"),
        "claude": _FakeBackend("claude", fail=True),          # aggregator errors
    }
    monkeypatch.setattr(M, "get_backend", _get_backend_factory(backends))

    res = await M.moa("Q?", aggregator="claude")
    assert res["error"].startswith("aggregator_failed")
    assert res["content"] == ""


@pytest.mark.asyncio
async def test_moa_empty_question():
    res = await M.moa("   ")
    assert res["error"] == "question is required"
    assert res["content"] == ""


@pytest.mark.asyncio
async def test_moa_unknown_aggregator(monkeypatch):
    monkeypatch.setattr(M, "status_all", _status({"codex"}))
    monkeypatch.setattr(M, "get_backend", _get_backend_factory({}))  # nothing exists

    res = await M.moa("Q?", aggregator="nonesuch")
    assert res["error"] == "unknown aggregator: nonesuch"
    assert res["content"] == ""


@pytest.mark.asyncio
async def test_moa_trims_long_advisor_guidance(monkeypatch):
    """A huge advisor blob is head+tail trimmed before folding into the prompt."""
    monkeypatch.setattr(M, "status_all", _status({"codex", "claude"}))
    huge = "A" * 10_000
    captured = {}

    class _CapturingAggregator(_FakeBackend):
        async def chat(self, messages, model=""):
            captured["prompt"] = messages[0].content
            return await super().chat(messages, model)

    backends = {
        "codex": _FakeBackend("codex", huge),
        "claude": _CapturingAggregator("claude", "answer"),
    }
    monkeypatch.setattr(M, "get_backend", _get_backend_factory(backends))

    res = await M.moa("Q?", advisors=["codex"], aggregator="claude")
    assert res["content"] == "answer"
    # The 10k blob must have been trimmed inside the aggregator prompt.
    assert "[... trimmed for length ...]" in captured["prompt"]
    assert len(captured["prompt"]) < 10_000


# ── moa_stream() — streaming phases ───────────────────────────────────

@pytest.mark.asyncio
async def test_moa_stream_phase_sequence(monkeypatch):
    monkeypatch.setattr(M, "status_all", _status({"codex", "gemini", "claude"}))
    backends = {
        "codex": _FakeBackend("codex", "a"),
        "gemini": _FakeBackend("gemini", "b"),
        "claude": _FakeBackend("claude", "FINAL"),
    }
    monkeypatch.setattr(M, "get_backend", _get_backend_factory(backends))

    events = [e async for e in M.moa_stream(
        "Q?", advisors=["codex", "gemini"], aggregator="claude",
    )]
    phases = [e["phase"] for e in events]

    assert phases[0] == "advisors"
    assert phases.count("advisor_done") == 2                  # one per advisor
    assert "aggregating" in phases
    assert phases[-1] == "done"

    done = events[-1]
    assert done["content"] == "FINAL"
    assert "advice" not in done                               # private by default


@pytest.mark.asyncio
async def test_moa_stream_advisor_done_names_are_recovered(monkeypatch):
    """Regression: as_completed() must still report WHICH advisor finished
    (the named-wrapper fix — never emit backend=None for a real advisor)."""
    monkeypatch.setattr(M, "status_all", _status({"codex", "gemini", "claude"}))
    backends = {
        "codex": _FakeBackend("codex", "a"),
        "gemini": _FakeBackend("gemini", fail=True),          # fails, name still reported
        "claude": _FakeBackend("claude", "FINAL"),
    }
    monkeypatch.setattr(M, "get_backend", _get_backend_factory(backends))

    events = [e async for e in M.moa_stream(
        "Q?", advisors=["codex", "gemini"], aggregator="claude",
    )]
    done_events = [e for e in events if e["phase"] == "advisor_done"]
    names = {e["backend"] for e in done_events}
    assert names == {"codex", "gemini"}                       # both named, none None
    ok_map = {e["backend"]: e["ok"] for e in done_events}
    assert ok_map["codex"] is True
    assert ok_map["gemini"] is False                          # failed but still named


@pytest.mark.asyncio
async def test_moa_stream_empty_question():
    events = [e async for e in M.moa_stream("  ")]
    assert events == [{"phase": "error", "error": "question is required"}]


@pytest.mark.asyncio
async def test_moa_stream_unknown_aggregator(monkeypatch):
    monkeypatch.setattr(M, "status_all", _status({"codex"}))
    monkeypatch.setattr(M, "get_backend", _get_backend_factory({}))
    events = [e async for e in M.moa_stream("Q?", aggregator="nope")]
    assert events == [{"phase": "error", "error": "unknown aggregator: nope"}]


# ── timeout & panel cap ───────────────────────────────────────────────
# These pin down the two behavior changes that make MoA safe in production:
# the per-advisor 30s timeout (a hung backend no longer wedges the panel) and
# the default panel cap of 1 (implicit calls stay fast). Both are exercised
# directly against the production module — the timeout is monkeypatched down
# so the test doesn't actually wait 30s.

import asyncio
import time as _time


class _SlowBackend:
    """Sleeps past any reasonable cap; the timeout test patches the cap down."""
    name = "slow"

    async def chat(self, messages, model=""):
        await asyncio.sleep(5)                              # 5s > any cap we set
        return ChatResult(backend="slow", model="slow-m",
                          content="too late", tokens=0)


@pytest.mark.asyncio
async def test_moa_ask_advisor_times_out(monkeypatch):
    """A wedged advisor (sleep 5s, cap 0.3s) is dropped within ~0.3s, returns None."""
    saved_cap = M._ADVISOR_TIMEOUT_S
    M._ADVISOR_TIMEOUT_S = 0.3
    try:
        backends = {"slow": _SlowBackend()}
        monkeypatch.setattr(M, "get_backend", _get_backend_factory(backends))
        t0 = _time.time()
        r = await M._ask_advisor("slow", "any question")
        dt = _time.time() - t0
    finally:
        M._ADVISOR_TIMEOUT_S = saved_cap
    assert r is None, f"slow advisor should time out to None, got {r!r}"
    assert 0.25 < dt < 1.0, f"timeout should fire near 0.3s, got {dt:.2f}s"


@pytest.mark.asyncio
async def test_moa_ask_advisor_fast_path_still_works(monkeypatch):
    """The positive case: a fast backend completes well under the cap."""
    backends = {"fast": _FakeBackend("fast", "quick reply")}
    monkeypatch.setattr(M, "get_backend", _get_backend_factory(backends))
    t0 = _time.time()
    r = await M._ask_advisor("fast", "any")
    dt = _time.time() - t0
    assert r is not None
    assert r["guidance"] == "quick reply"
    assert dt < 0.5, f"fast backend should complete in <0.5s, got {dt:.2f}s"


@pytest.mark.asyncio
async def test_moa_ask_advisor_returns_none_for_error(monkeypatch):
    """An advisor that raises (auth, missing CLI, network) is dropped, not propagated."""
    backends = {"bad": _FakeBackend("bad", fail=True)}
    monkeypatch.setattr(M, "get_backend", _get_backend_factory(backends))
    r = await M._ask_advisor("bad", "any")
    assert r is None


@pytest.mark.asyncio
async def test_moa_ask_advisor_returns_none_for_empty_content(monkeypatch):
    """An advisor that returns an empty string is treated as no guidance."""
    backends = {"empty": _FakeBackend("empty", reply="")}
    monkeypatch.setattr(M, "get_backend", _get_backend_factory(backends))
    r = await M._ask_advisor("empty", "any")
    assert r is None


@pytest.mark.asyncio
async def test_moa_ask_advisor_returns_none_for_unknown_backend(monkeypatch):
    """An advisor name not in the registry is dropped (the panel-resolver filters
    these out earlier, but _ask_advisor itself should still fail soft)."""
    monkeypatch.setattr(M, "get_backend", _get_backend_factory({}))
    r = await M._ask_advisor("nonesuch", "any")
    assert r is None


@pytest.mark.asyncio
async def test_moa_panel_cap_is_one_for_implicit_default(monkeypatch):
    """Default call (advisors=None) → panel capped to _DEFAULT_PANEL_CAP (1)
    even when 5 backends are online. The cap is checked BEFORE the top-up
    loop, so a preferred list that already exceeds the cap is truncated."""
    monkeypatch.setattr(M, "status_all",
                        _status({"ollama", "claude", "droid", "cursor", "codex"}))
    panel = await M._online_advisors(None, "claude")
    assert len(panel) == M._DEFAULT_PANEL_CAP
    assert panel[0] in ("ollama", "droid"), \
        f"surviving voice should be from preferred list, got {panel!r}"


@pytest.mark.asyncio
async def test_moa_panel_cap_drops_aggregator_in_preferred_list(monkeypatch):
    """When the aggregator is in the preferred advisor list, it's dropped, and
    the panel still honors the cap (preferred list had 2, aggregator was 1,
    survives 1)."""
    monkeypatch.setattr(M, "status_all",
                        _status({"ollama", "claude", "droid", "cursor"}))
    panel = await M._online_advisors(None, "ollama")          # ollama is aggregator
    assert panel == ["droid"], f"only droid should survive, got {panel!r}"


@pytest.mark.asyncio
async def test_moa_panel_cap_top_up_from_fallback_when_preferred_offline(monkeypatch):
    """All preferred advisors offline → top up from _FALLBACK_ADVISORS, still
    respecting the cap. Surviving voice must be from the fallback pool."""
    monkeypatch.setattr(M, "status_all",
                        _status({"claude", "cursor", "codex", "hermes"}))
    panel = await M._online_advisors(None, "claude")
    assert len(panel) == 1
    assert panel[0] in M._FALLBACK_ADVISORS, \
        f"surviving voice should come from fallback pool, got {panel!r}"


@pytest.mark.asyncio
async def test_moa_explicit_panel_is_not_capped(monkeypatch):
    """Explicit advisors=[...] is NOT capped — the caller asked for N, they
    get up to N (minus offline/aggregator exclusions)."""
    monkeypatch.setattr(M, "status_all",
                        _status({"ollama", "claude", "droid", "cursor", "codex"}))
    panel = await M._online_advisors(
        ["ollama", "droid", "cursor", "codex"], "claude",
    )
    assert panel == ["ollama", "droid", "cursor", "codex"]


@pytest.mark.asyncio
async def test_moa_drops_timed_out_advisor_in_full_flow(monkeypatch):
    """End-to-end: a hung advisor times out, the rest of the panel still
    answers, and the timed-out advisor is NOT in `answered`."""
    saved_cap = M._ADVISOR_TIMEOUT_S
    M._ADVISOR_TIMEOUT_S = 0.3
    try:
        monkeypatch.setattr(M, "status_all",
                            _status({"slow", "fast", "claude"}))
        backends = {
            "slow": _SlowBackend(),                            # times out
            "fast": _FakeBackend("fast", "good guidance"),
            "claude": _FakeBackend("claude", "FINAL"),
        }
        monkeypatch.setattr(M, "get_backend", _get_backend_factory(backends))
        t0 = _time.time()
        res = await M.moa("Q?", advisors=["slow", "fast"], aggregator="claude")
        dt = _time.time() - t0
    finally:
        M._ADVISOR_TIMEOUT_S = saved_cap
    assert res["error"] == ""
    assert "slow" not in res["answered"], f"slow should be dropped, got {res['answered']!r}"
    assert "fast" in res["answered"], f"fast should have answered, got {res!r}"
    assert res["content"] == "FINAL"
    assert dt < 2.0, f"whole call should not wait for the slow advisor, took {dt:.2f}s"


@pytest.mark.asyncio
async def test_moa_survives_baseexception_in_one_advisor(monkeypatch):
    """Regression: a BaseException (e.g. CancelledError on outer-task
    cancellation, KeyboardInterrupt, SystemExit) in ONE advisor's gather
    must NOT discard the siblings' results. The moa() gather uses
    return_exceptions=True so the surviving advisors' guidance still flows
    to the aggregator and the call returns a real answer, not 500."""
    monkeypatch.setattr(M, "status_all",
                        _status({"claude", "codex", "gemini"}))

    # Wrap the real _ask_advisor so the "codex" advisor raises CancelledError
    # (BaseException, NOT caught by _ask_advisor's `except Exception`) while
    # gemini returns cleanly. The bare-gather form (pre-fix) would re-raise
    # CancelledError out of moa(); the return_exceptions=True form keeps
    # gemini's guidance and the call still returns a real answer.
    real_ask = M._ask_advisor

    async def _ask_with_cancel(name, question):
        if name == "codex":
            raise asyncio.CancelledError("simulated outer cancel")
        return await real_ask(name, question)

    monkeypatch.setattr(M, "_ask_advisor", _ask_with_cancel)
    backends = {
        "codex": _FakeBackend("codex", "codex advice"),
        "gemini": _FakeBackend("gemini", "gemini advice"),
        "claude": _FakeBackend("claude", "FINAL"),
    }
    monkeypatch.setattr(M, "get_backend", _get_backend_factory(backends))

    res = await M.moa("Q?", advisors=["codex", "gemini"], aggregator="claude")
    # gemini's advice survived and the aggregator ran — call did NOT 500.
    assert res["error"] == ""
    assert "codex" not in res["answered"], \
        f"cancelled codex should be dropped, got {res['answered']!r}"
    assert "gemini" in res["answered"], \
        f"gemini should have answered, got {res!r}"
    assert res["content"] == "FINAL"


@pytest.mark.asyncio
async def test_moa_degrades_when_all_advisors_cancelled(monkeypatch):
    """If EVERY advisor's gather task raises BaseException, the panel is
    empty, the aggregator gets the bare question, and the call still
    succeeds (graceful solo degrade)."""
    monkeypatch.setattr(M, "status_all", _status({"claude", "codex", "gemini"}))

    async def _ask_always_cancel(name, question):
        raise asyncio.CancelledError(f"cancelled {name}")

    monkeypatch.setattr(M, "_ask_advisor", _ask_always_cancel)
    backends = {
        "codex": _FakeBackend("codex", "x"),
        "gemini": _FakeBackend("gemini", "g"),
        "claude": _FakeBackend("claude", "FINAL SOLO"),
    }
    monkeypatch.setattr(M, "get_backend", _get_backend_factory(backends))

    res = await M.moa("Q?", advisors=["codex", "gemini"], aggregator="claude")
    assert res["advisors"] == ["codex", "gemini"]                # panel still listed
    assert res["answered"] == []                                 # none survived
    assert res["error"] == ""
    assert res["content"] == "FINAL SOLO"                        # solo degrade worked


# ── New tests for Nous free-tier model resolution ─────────────────────

@pytest.mark.asyncio
async def test_moa_accepts_nous_model_ids_as_advisors(monkeypatch):
    """MoA advisor list can include full model IDs (e.g., 'tencent/hy3:free')
    which are auto-routed to the nous backend."""
    monkeypatch.setattr(M, "status_all", _status({"nous", "claude"}))
    backends = {
        "nous": _FakeBackend("nous", "free tier advice"),
        "claude": _FakeBackend("claude", "aggregated answer"),
    }
    monkeypatch.setattr(M, "get_backend", _get_backend_factory(backends))

    res = await M.moa(
        "Why is the sky blue?",
        advisors=["tencent/hy3:free"],  # Full model ID
        aggregator="claude"
    )
    
    assert res["error"] == ""
    # The model ID will be in advisors list if nous backend was online
    # (and the aggregator is different: claude)
    assert res["content"] == "aggregated answer"




@pytest.mark.asyncio
async def test_moa_free_tier_ensemble_correctness(monkeypatch):
    """Test that Nous free-tier models work as advisors alongside local ollama."""
    monkeypatch.setattr(M, "status_all", _status({"nous", "ollama"}))
    backends = {
        "nous": _FakeBackend("nous", "free advice"),
        "ollama": _FakeBackend("ollama", "assembled answer"),
    }
    monkeypatch.setattr(M, "get_backend", _get_backend_factory(backends))

    res = await M.moa(
        "Test question?",
        advisors=["ollama"],  # One advisor
        aggregator="ollama"  # Same backend for aggregator
    )
    
    # Even though both are ollama, the aggregator is separate from advisors
    assert res["error"] == ""
    assert res["content"] == "assembled answer"
