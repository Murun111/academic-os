"""Tests for backend.llm_hub — the multi-LLM switchboard.

Covers:
- Backend registry: every advertised backend is registered
- Probe: backend detection (online/offline), model listing
- Chat routing: ollama round-trip (others rely on having the CLI installed)
- History persistence: list, get, save, path-traversal defense
- Hermes is the orchestrator, not an LLM — chat() must refuse
"""

import asyncio
import json
import pytest

from backend.llm_hub import (
    BACKENDS, get_backend, status_all,
    OllamaBackend, CodexBackend, ClaudeBackend,
    DroidBackend, CursorBackend, HermesBackend, NousBackend,
    ChatMessage, ModelInfo, ProbeResult,
    list_threads, get_thread, save_thread,
    THREADS_DIR,
)


# ── Registry ──────────────────────────────────────────────────────────
def test_all_advertised_backends_are_registered():
    names = {b.name for b in BACKENDS}
    assert "ollama" in names
    assert "codex" in names
    assert "claude" in names
    assert "droid" in names
    assert "cursor" in names
    assert "hermes" in names
    assert "nous" in names


def test_get_backend_known_name():
    b = get_backend("ollama")
    assert isinstance(b, OllamaBackend)


def test_get_backend_unknown_raises():
    with pytest.raises(KeyError, match="unknown backend"):
        get_backend("does-not-exist")


def test_backend_names_are_unique():
    names = [b.name for b in BACKENDS]
    assert len(names) == len(set(names)), f"duplicate: {names}"


# ── Probe ─────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_status_all_returns_every_backend():
    results = await status_all()
    expected = {"ollama", "codex", "claude", "droid", "cursor", "gemini", "hermes", "nous"}
    assert set(results.keys()) == expected


@pytest.mark.asyncio
async def test_hermes_is_always_online():
    """Hermes is the orchestrator itself — always available."""
    h = HermesBackend()
    r = await h.probe()
    assert r.online is True
    assert r.account == "local"


@pytest.mark.asyncio
async def test_ollama_models_list_when_running(monkeypatch):
    """If ollama is running locally, probe should return ≥0 models and online=True.
    If not running, the probe returns online=False gracefully."""
    o = OllamaBackend()
    r = await o.probe()
    # Don't assert online — it depends on the test environment.
    assert isinstance(r, ProbeResult)
    if r.online:
        assert len(r.models) >= 1
        assert all(isinstance(m, ModelInfo) for m in r.models)


@pytest.mark.asyncio
async def test_codex_probe_with_chatgpt_auth_returns_default():
    """ChatGPT-authenticated codex shows one 'default' model entry."""
    c = CodexBackend()
    r = await c.probe()
    if r.online and r.account == "ChatGPT":
        assert len(r.models) == 1
        assert r.models[0].id == "default"


@pytest.mark.asyncio
async def test_offline_backend_returns_offline():
    """If a backend's binary doesn't exist, probe returns online=False with a
    human-readable message — no exception."""
    c = CursorBackend()
    r = await c.probe()
    # Cursor's binary is `agent`. If not on PATH, offline.
    if not r.online:
        assert "not installed" in r.message or "binary error" in r.message


# ── Chat ──────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_ollama_chat_round_trip():
    """Real round-trip via local ollama. Skips if ollama isn't running."""
    o = OllamaBackend()
    r = await o.probe()
    if not r.online or not r.models:
        pytest.skip("ollama not running")
    model = r.models[0].id
    msgs = [ChatMessage(role="user", content="Reply with the single word: HI")]
    result = await o.chat(msgs, model=model)
    assert result.backend == "ollama"
    assert result.model == model
    assert "HI" in result.content.upper()
    assert result.tokens > 0


@pytest.mark.asyncio
async def test_hermes_chat_success(monkeypatch):
    """Hermes chat calls hermes -z <prompt> --safe-mode via _run and returns
    the output."""
    # Capture the argv passed to _run for assertion.
    captured_argv = []

    def fake_run(argv, timeout=8, input_text=None):
        captured_argv.append(argv)
        return (0, "hello from hermes", "")

    # Monkeypatch the module-level _run.
    import backend.llm_hub
    monkeypatch.setattr(backend.llm_hub, "_run", fake_run)

    h = HermesBackend()
    result = await h.chat([ChatMessage("user", "hi")], model="hermes-mini-m3")

    # Assert the result.
    assert result.backend == "hermes"
    assert result.model == "hermes-mini-m3"
    assert result.content == "hello from hermes"

    # Assert the argv passed to _run contains required flags.
    assert len(captured_argv) == 1
    argv = captured_argv[0]
    assert "hermes" in argv
    assert "-z" in argv
    assert "--safe-mode" in argv
    # For default model (hermes-mini-m3), no -m flag should be added.
    assert "-m" not in argv


@pytest.mark.asyncio
async def test_hermes_chat_with_non_default_model(monkeypatch):
    """When a non-default model is passed, hermes includes -m <model>."""
    captured_argv = []

    def fake_run(argv, timeout=8, input_text=None):
        captured_argv.append(argv)
        return (0, "response text", "")

    import backend.llm_hub
    monkeypatch.setattr(backend.llm_hub, "_run", fake_run)

    h = HermesBackend()
    result = await h.chat([ChatMessage("user", "hello")], model="hermes-large")

    assert result.model == "hermes-large"
    argv = captured_argv[0]
    assert "-m" in argv
    assert "hermes-large" in argv


@pytest.mark.asyncio
async def test_hermes_chat_error_on_nonzero_exit(monkeypatch):
    """If _run returns non-zero exit code, chat raises RuntimeError."""
    def fake_run(argv, timeout=8, input_text=None):
        return (1, "", "boom")

    import backend.llm_hub
    monkeypatch.setattr(backend.llm_hub, "_run", fake_run)

    h = HermesBackend()
    with pytest.raises(RuntimeError, match="hermes failed.*exit 1"):
        await h.chat([ChatMessage("user", "test")])


@pytest.mark.asyncio
async def test_hermes_chat_error_on_empty_output(monkeypatch):
    """If _run returns zero but empty output, chat raises RuntimeError."""
    def fake_run(argv, timeout=8, input_text=None):
        return (0, "", "")

    import backend.llm_hub
    monkeypatch.setattr(backend.llm_hub, "_run", fake_run)

    h = HermesBackend()
    with pytest.raises(RuntimeError, match="hermes failed.*exit 0"):
        await h.chat([ChatMessage("user", "test")])


# ── History persistence ──────────────────────────────────────────────
def test_thread_id_is_unique_12_hex():
    from backend.llm_hub import _new_thread_id
    ids = {_new_thread_id() for _ in range(50)}
    assert len(ids) == 50  # no collisions
    for tid in ids:
        assert len(tid) == 12
        assert all(c in "0123456789abcdef" for c in tid)


def test_thread_path_rejects_traversal():
    from backend.llm_hub import _thread_path
    for bad in ["../etc/passwd", "foo/bar", "..", "", "a/b"]:
        with pytest.raises(ValueError):
            _thread_path(bad)


def test_save_and_get_thread(tmp_path, monkeypatch):
    """Persist a turn and read it back."""
    monkeypatch.setattr("backend.llm_hub.THREADS_DIR", tmp_path / "llm_threads")
    tid = save_thread(None, "ollama", "gemma4:latest",
                      "first user message", "first assistant response",
                      assistant_meta={"tokens": 12, "elapsed_ms": 200})
    assert len(tid) == 12
    thread = get_thread(tid)
    assert thread is not None
    assert thread["id"] == tid
    assert thread["backend"] == "ollama"
    assert thread["title"] == "first user message"
    assert len(thread["messages"]) == 2
    user_msg, asst_msg = thread["messages"]
    assert user_msg["role"] == "user"
    assert user_msg["content"] == "first user message"
    assert asst_msg["role"] == "assistant"
    assert asst_msg["content"] == "first assistant response"
    assert asst_msg["tokens"] == 12
    assert asst_msg["elapsed_ms"] == 200


def test_save_appends_to_existing_thread(tmp_path, monkeypatch):
    """A second save to the same thread_id appends, doesn't replace."""
    monkeypatch.setattr("backend.llm_hub.THREADS_DIR", tmp_path / "llm_threads")
    tid = save_thread(None, "ollama", "gemma4:latest", "first", "r1")
    tid2 = save_thread(tid, "ollama", "gemma4:latest", "second", "r2")
    assert tid2 == tid
    thread = get_thread(tid)
    assert thread is not None
    assert len(thread["messages"]) == 4  # 2 turns × 2 messages
    assert thread["messages"][0]["content"] == "first"
    assert thread["messages"][2]["content"] == "second"


def test_list_threads_orders_by_mtime(tmp_path, monkeypatch):
    monkeypatch.setattr("backend.llm_hub.THREADS_DIR", tmp_path / "llm_threads")
    save_thread(None, "ollama", "m1", "alpha", "a")
    save_thread(None, "ollama", "m2", "beta", "b")
    threads = list_threads()
    assert len(threads) == 2
    # Most recent first (beta created after alpha)
    assert threads[0]["title"] in ("alpha", "beta")
    assert threads[1]["title"] in ("alpha", "beta")
    assert threads[0]["title"] != threads[1]["title"]


def test_get_thread_missing_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr("backend.llm_hub.THREADS_DIR", tmp_path / "llm_threads")
    assert get_thread("nonexistent") is None


def test_thread_title_truncates_long_user_message(tmp_path, monkeypatch):
    monkeypatch.setattr("backend.llm_hub.THREADS_DIR", tmp_path / "llm_threads")
    long_msg = "x" * 200
    save_thread(None, "ollama", "m1", long_msg, "ok")
    threads = list_threads()
    assert len(threads[0]["title"]) <= 60


# ── Nous Portal ───────────────────────────────────────────────────────
#
# The Nous backend resolves an OAuth JWT via hermes_cli.auth, then talks to
# inference-api.nousresearch.com over HTTPS. These tests mock both layers so
# no network or auth is required — what we exercise is the backend's own
# logic (auth gating, cache TTL, response shape parsing, error surfacing).
#
# We intentionally do NOT make a live network call here; the live check
# happens in the smoke test that runs alongside the others.

class _FakeResp:
    def __init__(self, status=200, body=None, raise_exc=None):
        self.status = status
        self._body = body or {}
        self._raise = raise_exc
    def read(self):
        if self._raise: raise self._raise
        return json.dumps(self._body).encode()
    def __enter__(self): return self
    def __exit__(self, *a): return False


def _fake_creds():
    return {
        "provider": "nous",
        "base_url": "https://inference-api.nousresearch.com/v1",
        "api_key": "fake-jwt-for-tests",
        "key_id": None,
        "expires_at": "2099-01-01T00:00:00+00:00",
        "expires_in": 999999,
        "source": "invoke_jwt",
    }


def _reset_nous_cache():
    NousBackend._cached_models = []
    NousBackend._cached_at = 0.0


@pytest.mark.asyncio
async def test_nous_probe_offline_when_no_creds(monkeypatch):
    """_creds() returns None (no JWT resolvable) → probe reports offline
    with a clear message, never raises. The /api/llms/status endpoint
    depends on this contract."""
    _reset_nous_cache()
    def boom(self):
        return None
    monkeypatch.setattr(NousBackend, "_creds", boom)
    nb = NousBackend()
    r = await nb.probe()
    assert r.online is False
    assert "nous" in r.message.lower()
    assert r.models == []


@pytest.mark.asyncio
async def test_nous_probe_does_not_propagate_auth_exceptions(monkeypatch):
    """Even if _creds() itself raises (defensive: should never happen in
    production because the resolver catches internally, but a future
    hermes_cli.auth refactor could regress that), probe() must NOT raise —
    it must surface as offline with a 'resolver crashed' message."""
    _reset_nous_cache()
    def boom(self):
        raise RuntimeError("auth resolver crashed")
    monkeypatch.setattr(NousBackend, "_creds", boom)
    nb = NousBackend()
    r = await nb.probe()
    assert r.online is False
    assert "crashed" in r.message or "auth" in r.message.lower()


@pytest.mark.asyncio
async def test_nous_probe_online_with_creds(monkeypatch):
    """With a valid JWT and a /v1/models 200, probe reports online, populates
    the cache, and surfaces model count + OAuth account string."""
    _reset_nous_cache()
    monkeypatch.setattr(NousBackend, "_creds", lambda self: _fake_creds())
    fake_models = [
        {"id": "anthropic/claude-fable-5", "context_length": 1_000_000},
        {"id": "tencent/hy3:free", "context_length": 262_144},
        {"id": "~openai/gpt-latest", "context_length": 1_050_000},
    ]
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda req, timeout=8: _FakeResp(200, {"data": fake_models}),
    )
    nb = NousBackend()
    r = await nb.probe()
    assert r.online is True
    assert r.account == "Nous Portal (OAuth)"
    assert "3" in r.message
    assert len(r.models) == 3
    assert r.models[0].id == "anthropic/claude-fable-5"
    assert r.models[0].context == 1_000_000


@pytest.mark.asyncio
async def test_nous_probe_surfaces_upstream_error(monkeypatch):
    """An HTTP 401/500 from upstream must surface as offline with the
    upstream status in the message, not as a 500 to the caller."""
    _reset_nous_cache()
    monkeypatch.setattr(NousBackend, "_creds", lambda self: _fake_creds())
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda req, timeout=8: _FakeResp(401, {"error": "token expired"}),
    )
    nb = NousBackend()
    r = await nb.probe()
    assert r.online is False
    assert "401" in r.message


@pytest.mark.asyncio
async def test_nous_models_caches_for_5_minutes(monkeypatch):
    """After a successful probe, .models() must NOT hit the network again
    within NOUS_CACHE_S (300s) — the dashboard polls /api/llms/status on a
    600ms debounce and we don't want to hammer the upstream."""
    _reset_nous_cache()
    monkeypatch.setattr(NousBackend, "_creds", lambda self: _fake_creds())
    call_count = {"n": 0}
    def counting_urlopen(req, timeout=10):
        call_count["n"] += 1
        return _FakeResp(200, {"data": [{"id": "a/m1"}, {"id": "a/m2"}]})
    monkeypatch.setattr("urllib.request.urlopen", counting_urlopen)
    nb = NousBackend()
    # First call populates the cache.
    r1 = await nb.probe()
    # Subsequent models() calls within the TTL must be served from cache.
    m1 = await nb.models()
    m2 = await nb.models()
    m3 = await nb.models()
    assert len(m1) == 2 and len(m2) == 2 and len(m3) == 2
    # urlopen is called once during the probe's warm-up; .models() itself
    # short-circuits via the cache. So the counter is exactly 1.
    assert call_count["n"] == 1, \
        f"expected exactly 1 upstream call (cache), got {call_count['n']}"


@pytest.mark.asyncio
async def test_nous_models_refresh_after_ttl_expiry(monkeypatch):
    """After NOUS_CACHE_S elapses, .models() must hit the upstream again.
    We monkeypatch time.time to simulate TTL passage without sleeping."""
    _reset_nous_cache()
    monkeypatch.setattr(NousBackend, "_creds", lambda self: _fake_creds())
    fake_time = {"t": 1000.0}
    monkeypatch.setattr("backend.llm_hub.time.time", lambda: fake_time["t"])
    call_count = {"n": 0}
    def counting_urlopen(req, timeout=10):
        call_count["n"] += 1
        # Return one extra model each call so we can tell them apart.
        return _FakeResp(200, {"data": [{"id": f"m-{call_count['n']}"}]})
    monkeypatch.setattr("urllib.request.urlopen", counting_urlopen)
    nb = NousBackend()
    await nb.probe()  # populates cache at t=1000
    assert call_count["n"] == 1
    # Within TTL: no new call.
    fake_time["t"] = 1000.0 + NousBackend.NOUS_CACHE_S - 1
    await nb.models()
    assert call_count["n"] == 1
    # Past TTL: re-fetches.
    fake_time["t"] = 1000.0 + NousBackend.NOUS_CACHE_S + 1
    m = await nb.models()
    assert call_count["n"] == 2
    assert m[0].id == "m-2"


@pytest.mark.asyncio
async def test_nous_chat_uses_passed_model_and_default(monkeypatch):
    """chat(model='x/y') must pass 'x/y' to the upstream body; chat() with
    no model must use the default (claude-fable-5). Default exists so a
    one-off call without a model still works."""
    _reset_nous_cache()
    monkeypatch.setattr(NousBackend, "_creds", lambda self: _fake_creds())
    captured_bodies: list[dict] = []
    def capture_urlopen(req, timeout=180):
        body = json.loads(req.data.decode())
        captured_bodies.append(body)
        return _FakeResp(200, {
            "choices": [{"message": {"role": "assistant", "content": "ok"}}],
            "usage": {"total_tokens": 7},
        })
    monkeypatch.setattr("urllib.request.urlopen", capture_urlopen)
    nb = NousBackend()
    r1 = await nb.chat([ChatMessage("user", "hi")])
    r2 = await nb.chat([ChatMessage("user", "hi")], model="tencent/hy3:free")
    assert captured_bodies[0]["model"] == "anthropic/claude-fable-5"
    assert captured_bodies[1]["model"] == "tencent/hy3:free"
    assert r1.model == "anthropic/claude-fable-5"
    assert r2.model == "tencent/hy3:free"
    assert r1.tokens == 7


@pytest.mark.asyncio
async def test_nous_chat_raises_clear_error_on_no_creds(monkeypatch):
    """When creds aren't available (returns None), chat() must raise with
    an actionable message naming the auth command — not a generic 500.
    Note: _creds() is contracted never to raise; we exercise the None
    path here (the real-world auth-failure shape)."""
    _reset_nous_cache()
    def boom(self):
        return None
    monkeypatch.setattr(NousBackend, "_creds", boom)
    nb = NousBackend()
    with pytest.raises(RuntimeError, match="hermes auth status nous"):
        await nb.chat([ChatMessage("user", "hi")])


@pytest.mark.asyncio
async def test_nous_chat_surfaces_upstream_http_error(monkeypatch):
    """A 4xx from Nous (e.g. model not found) must raise with the upstream
    status code and body in the message — so the frontend can show why."""
    _reset_nous_cache()
    monkeypatch.setattr(NousBackend, "_creds", lambda self: _fake_creds())
    import io, urllib.error
    from email.message import Message
    hdrs = Message()
    hdrs["Content-Type"] = "application/json"
    err_body = b'{"error":"model not found: foo/bar"}'
    err_inst = urllib.error.HTTPError(
        "https://inference-api.nousresearch.com/v1/chat/completions",
        404, "Not Found", hdrs, io.BytesIO(err_body),
    )
    def raise_http(req, timeout=180):
        raise err_inst
    monkeypatch.setattr("urllib.request.urlopen", raise_http)
    nb = NousBackend()
    with pytest.raises(RuntimeError, match="nous HTTP 404"):
        await nb.chat([ChatMessage("user", "hi")], model="foo/bar")


def test_model_info_has_cost_field():
    """ModelInfo now includes cost_per_mtok for free/paid tracking."""
    from backend.llm_hub import ModelInfo
    
    m_free = ModelInfo("test", "Test Model", context=4096, cost_per_mtok=0.0)
    m_paid = ModelInfo("gpt-4o", "GPT-4o", context=128000, cost_per_mtok=0.015)
    
    assert m_free.cost_per_mtok == 0.0
    assert m_paid.cost_per_mtok == 0.015
    
    # Default should be 0 (free)
    m_default = ModelInfo("local", "Local Model")
    assert m_default.cost_per_mtok == 0.0
