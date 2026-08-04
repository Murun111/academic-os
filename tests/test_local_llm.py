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
