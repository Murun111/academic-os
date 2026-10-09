"""Tests for the bundled local AI service (llama.cpp integration)."""
import json

import pytest

from backend.services import local_llm
from backend.ollama import ChatMessage, ToolCall, _parse_message


def test_to_openai_messages_roundtrip_shapes():
    msgs = [
        ChatMessage(role="system", content="be brief"),
        ChatMessage(role="user", content="hi"),
        ChatMessage(role="assistant", content="",
                    tool_calls=[ToolCall(id="c1", name="web.search",
                                         arguments={"query": "x"})]),
        ChatMessage(role="tool", content='{"ok": true}', tool_call_id="c1"),
    ]
    out = local_llm.to_openai_messages(msgs)
    assert out[0] == {"role": "system", "content": "be brief"}
    tc = out[2]["tool_calls"][0]
    assert tc["type"] == "function"
    assert tc["function"]["name"] == "web.search"
    assert json.loads(tc["function"]["arguments"]) == {"query": "x"}
    assert out[3]["tool_call_id"] == "c1"


def test_from_openai_response_parses_via_existing_parser():
    openai = {
        "model": "qwen",
        "choices": [{"finish_reason": "tool_calls", "message": {
            "role": "assistant", "content": None,
            "tool_calls": [{"id": "call_0", "type": "function", "function": {
                "name": "academics.add_application",
                "arguments": '{"name": "Gates Scholarship"}'}}],
        }}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 20},
    }
    raw = local_llm.from_openai_response(openai)
    msg = _parse_message(raw)  # the ollama.py parser must accept this shape
    assert msg.tool_calls[0].name == "academics.add_application"
    assert msg.tool_calls[0].arguments == {"name": "Gates Scholarship"}
    assert raw["prompt_eval_count"] == 100


def test_status_reports_missing_model(monkeypatch, tmp_path):
    monkeypatch.setenv("ACADEMIC_OS_DATA", str(tmp_path))
    s = local_llm.status()
    assert s["model"] is None
    assert s["running"] is False or isinstance(s["running"], bool)
    assert set(s["models"].keys()) == {"standard", "small"}
    assert s["models"]["standard"]["size_mb"] > 2000


def test_installed_model_requires_exact_size(monkeypatch, tmp_path):
    monkeypatch.setenv("ACADEMIC_OS_DATA", str(tmp_path))
    f = local_llm.models_dir() / local_llm.MODELS["small"]["file"]
    f.write_bytes(b"truncated")  # wrong size → not installed
    assert local_llm.installed_model() is None


def test_download_rejects_unknown_model(monkeypatch, tmp_path):
    monkeypatch.setenv("ACADEMIC_OS_DATA", str(tmp_path))
    assert local_llm.download_model("gpt5")["error"] == "unknown_model"


def test_binary_path_found_in_vendor():
    # vendor/llama/llama-server is fetched by the build; present in this repo
    p = local_llm.binary_path()
    assert p is not None and p.name == "llama-server"


# ── F54 / F55 / F60 / F70 regressions ────────────────────────────────

def test_status_marks_stale_download_interrupted(monkeypatch, tmp_path):
    """F54: 'downloading' progress with no live thread must not poll forever."""
    monkeypatch.setenv("ACADEMIC_OS_DATA", str(tmp_path))
    monkeypatch.setattr(local_llm, "_download_thread", None)
    local_llm._progress_path().write_text(json.dumps(
        {"model": "standard", "pct": 35.0, "done": False, "error": None}))
    dl = local_llm.status()["download"]
    assert dl["error"] and "interrupted" in dl["error"]


def _fake_model(monkeypatch, data: bytes):
    import hashlib
    spec = {"label": "t", "file": "t.gguf", "url": "http://x/t.gguf",
            "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    monkeypatch.setattr(local_llm, "MODELS", {"standard": spec, "small": spec})
    return spec


class _Resp:
    def __init__(self, status, body):
        self.status_code, self._body = status, body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def iter_bytes(self, n):
        yield self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _run_download():
    r = local_llm.download_model("standard")
    assert r.get("ok"), r
    local_llm._download_thread.join(10)
    return json.loads(local_llm._progress_path().read_text())


def test_download_complete_part_goes_straight_to_verify(monkeypatch, tmp_path):
    monkeypatch.setenv("ACADEMIC_OS_DATA", str(tmp_path))
    data = b"0123456789"
    spec = _fake_model(monkeypatch, data)
    part = local_llm.models_dir() / "t.part"
    part.write_bytes(data)

    def _no_http(*a, **k):  # pragma: no cover
        raise AssertionError("must not request a Range past the end (416)")
    monkeypatch.setattr(local_llm.httpx, "stream", _no_http)
    prog = _run_download()
    assert prog["done"] is True, prog
    assert (local_llm.models_dir() / spec["file"]).read_bytes() == data


def test_download_restarts_when_server_ignores_range(monkeypatch, tmp_path):
    monkeypatch.setenv("ACADEMIC_OS_DATA", str(tmp_path))
    data = b"0123456789"
    spec = _fake_model(monkeypatch, data)
    (local_llm.models_dir() / "t.part").write_bytes(data[:4])
    # CDN answers 200 with the full body to a Range request
    monkeypatch.setattr(local_llm.httpx, "stream", lambda *a, **k: _Resp(200, data))
    prog = _run_download()
    assert prog["done"] is True, prog
    assert (local_llm.models_dir() / spec["file"]).read_bytes() == data


def test_download_deletes_oversized_part(monkeypatch, tmp_path):
    monkeypatch.setenv("ACADEMIC_OS_DATA", str(tmp_path))
    data = b"0123456789"
    _fake_model(monkeypatch, data)
    (local_llm.models_dir() / "t.part").write_bytes(data + b"EXTRA")
    monkeypatch.setattr(local_llm.httpx, "stream", lambda *a, **k: _Resp(200, data))
    prog = _run_download()
    assert prog["done"] is True, prog


def test_ensure_running_spawns_once_for_concurrent_callers(monkeypatch, tmp_path):
    import threading
    import time as _t
    real_sleep = _t.sleep
    monkeypatch.setenv("ACADEMIC_OS_DATA", str(tmp_path))
    monkeypatch.setattr(local_llm, "_proc", None)
    monkeypatch.setattr(local_llm, "binary_path", lambda: tmp_path / "bin")
    monkeypatch.setattr(local_llm, "installed_model", lambda: ("small", tmp_path / "m"))
    state = {"up": False, "popen": 0}

    class _P:
        def poll(self):
            return None

    def _popen(*a, **k):
        state["popen"] += 1
        threading.Timer(0.3, lambda: state.update(up=True)).start()
        return _P()

    monkeypatch.setattr(local_llm.subprocess, "Popen", _popen)
    monkeypatch.setattr(local_llm, "server_running", lambda: state["up"])
    monkeypatch.setattr(local_llm.time, "sleep", lambda s: real_sleep(0.05))
    res = []
    ts = [threading.Thread(target=lambda: res.append(local_llm.ensure_running(5))) for _ in range(3)]
    [t.start() for t in ts]
    [t.join(10) for t in ts]
    assert state["popen"] == 1 and res == [True, True, True]


def test_stop_terminates_orphaned_llama_server(monkeypatch):
    import signal
    monkeypatch.setattr(local_llm, "_proc", None)
    state = {"up": True}
    monkeypatch.setattr(local_llm, "server_running", lambda: state["up"])
    monkeypatch.setattr(local_llm, "_port_listener_pids", lambda: [4242])
    killed = []
    monkeypatch.setattr(local_llm.os, "kill",
                        lambda pid, sig: (killed.append((pid, sig)), state.update(up=False)))
    assert local_llm.stop() is True
    assert killed == [(4242, signal.SIGTERM)]


def test_stop_reports_failure_when_still_running(monkeypatch):
    monkeypatch.setattr(local_llm, "_proc", None)
    monkeypatch.setattr(local_llm, "server_running", lambda: True)
    monkeypatch.setattr(local_llm, "_port_listener_pids", lambda: [])
    monkeypatch.setattr(local_llm.time, "sleep", lambda s: None)
    assert local_llm.stop() is False
