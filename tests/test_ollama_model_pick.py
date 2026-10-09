"""F71: Ollama up but the built-in default model (gemma4:latest) missing.

Hermetic: an httpx MockTransport stands in for the Ollama server.
"""
import httpx
import pytest

from backend.ollama import ChatMessage, OllamaService


def _svc(installed, monkeypatch, seen):
    monkeypatch.delenv("OLLAMA_DEFAULT_MODEL", raising=False)

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": n} for n in installed]})
        if req.url.path == "/api/chat":
            import json
            model = json.loads(req.content)["model"]
            seen.append(model)
            if model not in installed:
                return httpx.Response(404, json={"error": "model not found"})
            return httpx.Response(200, json={"message": {"role": "assistant", "content": "hi"},
                                             "model": model})
        return httpx.Response(404)

    svc = OllamaService(base_url="http://x")
    svc._client = httpx.AsyncClient(base_url="http://x", transport=httpx.MockTransport(handler))
    return svc


@pytest.mark.asyncio
async def test_health_true_with_other_chat_model(monkeypatch):
    svc = _svc(["nomic-embed-text:latest", "llama3:8b"], monkeypatch, [])
    assert await svc.health() is True


@pytest.mark.asyncio
async def test_chat_falls_over_to_installed_model_on_404(monkeypatch):
    seen = []
    svc = _svc(["nomic-embed-text:latest", "llama3:8b"], monkeypatch, seen)
    resp = await svc.chat([ChatMessage(role="user", content="x")])
    assert resp.message.content == "hi"
    assert seen == ["gemma4:latest", "llama3:8b"]
    assert svc.model == "llama3:8b"


@pytest.mark.asyncio
async def test_explicit_env_model_is_not_swapped(monkeypatch):
    seen = []
    svc = _svc(["llama3:8b"], monkeypatch, seen)
    svc._model_is_default = False  # user chose gemma4 explicitly
    with pytest.raises(httpx.HTTPStatusError):
        await svc.chat([ChatMessage(role="user", content="x")])
    assert seen == ["gemma4:latest"]
