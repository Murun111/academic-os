"""Bundled local AI — llama.cpp server lifecycle + model download.

Makes AI work with nothing pre-installed: the app ships the ~50MB
llama-server binary (vendor/llama/, copied into the .app by build_dmg.sh);
the model weights download on demand into ~/.academic-os/models/ with
resumable progress. OllamaService falls back to this server transparently
when Ollama isn't installed, so every existing feature (essay feedback,
agents, chat) works unchanged.

The server speaks the OpenAI chat API on 127.0.0.1:11435 (--jinja enables
tool calling). Nothing here ever leaves the machine except the one model
download from Hugging Face.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import httpx

PORT = int(os.environ.get("LOCAL_LLM_PORT", "11435"))
BASE_URL = f"http://127.0.0.1:{PORT}"

MODELS = {
    "standard": {
        "label": "Qwen3 4B (recommended)",
        "file": "qwen3-4b-instruct-q4_k_m.gguf",
        "url": ("https://huggingface.co/bartowski/Qwen_Qwen3-4B-Instruct-2507-GGUF"
                "/resolve/main/Qwen_Qwen3-4B-Instruct-2507-Q4_K_M.gguf"),
        "size": 2497280736,
        "sha256": "2fde00ce69dd4899c70d020845e2638353015bba0fdf161b3eb965f2bca4464e",
    },
    "small": {
        "label": "Qwen2.5 0.5B (fast, weak laptops)",
        "file": "qwen2.5-0.5b-instruct-q4_k_m.gguf",
        "url": ("https://huggingface.co/bartowski/Qwen2.5-0.5B-Instruct-GGUF"
                "/resolve/main/Qwen2.5-0.5B-Instruct-Q4_K_M.gguf"),
        "size": 397808192,
        "sha256": "6eb923e7d26e9cea28811e1a8e852009b21242fb157b26149d3b188f3a8c8653",
    },
}

_proc: subprocess.Popen | None = None
_download_thread: threading.Thread | None = None
_start_thread: threading.Thread | None = None
_start_lock = threading.Lock()
_starting = False
_start_error: str | None = None


# ── paths ─────────────────────────────────────────────────────────

def binary_path() -> Path | None:
    """Locate llama-server: frozen bundle first, then repo vendor/."""
    candidates = []
    if getattr(sys, "frozen", False):
        candidates.append(Path(sys.executable).parent / "_internal" / "vendor" / "llama" / "llama-server")
        candidates.append(Path(sys.executable).parent / "vendor" / "llama" / "llama-server")
    candidates.append(Path(__file__).resolve().parent.parent.parent / "vendor" / "llama" / "llama-server")
    for c in candidates:
        if c.is_file():
            return c
    return None


def models_dir() -> Path:
    from backend.vault import resolve_vault_path
    d = resolve_vault_path() / "models"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _progress_path() -> Path:
    return models_dir() / "_download_progress.json"


def installed_model() -> tuple[str, Path] | None:
    """Best installed model, preferring the larger one."""
    for key in ("standard", "small"):
        p = models_dir() / MODELS[key]["file"]
        if p.is_file() and p.stat().st_size == MODELS[key]["size"]:
            return key, p
    return None


# ── status ────────────────────────────────────────────────────────

def server_running() -> bool:
    try:
        r = httpx.get(f"{BASE_URL}/health", timeout=2)
        return r.status_code == 200
    except Exception:
        return False


def status() -> dict:
    prog = None
    if _progress_path().exists():
        try:
            prog = json.loads(_progress_path().read_text())
        except (json.JSONDecodeError, OSError):
            pass
    inst = installed_model()
    return {
        "binary": binary_path() is not None,
        "model": inst[0] if inst else None,
        "models": {k: {"label": m["label"], "size_mb": m["size"] // (1024 * 1024),
                       "installed": (models_dir() / m["file"]).is_file()}
                   for k, m in MODELS.items()},
        "download": prog,
        "running": server_running(),
        "starting": _starting,
        "start_error": _start_error,
        "port": PORT,
    }


# ── model download (background thread, progress file) ─────────────

def download_model(key: str) -> dict:
    global _download_thread
    if key not in MODELS:
        return {"error": "unknown_model"}
    if _download_thread and _download_thread.is_alive():
        return {"error": "download_in_progress"}
    spec = MODELS[key]
    target = models_dir() / spec["file"]
    if target.is_file() and target.stat().st_size == spec["size"]:
        return {"ok": True, "already": True}

    def _run() -> None:
        part = target.with_suffix(".part")
        try:
            resume = part.stat().st_size if part.exists() else 0
            headers = {"Range": f"bytes={resume}-"} if resume else {}
            mode = "ab" if resume else "wb"
            with httpx.stream("GET", spec["url"], headers=headers,
                              follow_redirects=True, timeout=60) as r:
                r.raise_for_status()
                got = resume
                with open(part, mode) as f:
                    for chunk in r.iter_bytes(1024 * 512):
                        f.write(chunk)
                        got += len(chunk)
                        _progress_path().write_text(json.dumps({
                            "model": key, "pct": round(got / spec["size"] * 100, 1),
                            "done": False, "error": None}))
            if part.stat().st_size != spec["size"]:
                raise IOError(f"size mismatch: {part.stat().st_size} != {spec['size']}")
            expected_sha256 = spec.get("sha256")
            if expected_sha256:
                _progress_path().write_text(json.dumps(
                    {"model": key, "pct": 100.0, "done": False, "error": None,
                     "verifying": True}))
                digest = hashlib.sha256()
                with open(part, "rb") as f:
                    for chunk in iter(lambda: f.read(1024 * 1024), b""):
                        digest.update(chunk)
                if digest.hexdigest() != expected_sha256:
                    part.unlink(missing_ok=True)
                    raise IOError("checksum mismatch — download corrupted, please retry")
            part.rename(target)
            _progress_path().write_text(json.dumps(
                {"model": key, "pct": 100.0, "done": True, "error": None}))
        except Exception as e:
            _progress_path().write_text(json.dumps(
                {"model": key, "pct": None, "done": False,
                 "error": f"{type(e).__name__}: {e}"}))

    _progress_path().write_text(json.dumps(
        {"model": key, "pct": 0.0, "done": False, "error": None}))
    _download_thread = threading.Thread(target=_run, daemon=True)
    _download_thread.start()
    return {"ok": True, "started": key}


# ── server lifecycle ──────────────────────────────────────────────

def ensure_running(wait_seconds: int = 90) -> bool:
    """Start llama-server if binary+model exist. Blocks until healthy."""
    global _proc
    if server_running():
        return True
    binary = binary_path()
    inst = installed_model()
    if binary is None or inst is None:
        return False
    if _proc is not None and _proc.poll() is None:
        pass  # starting up already
    else:
        _proc = subprocess.Popen(
            [str(binary), "-m", str(inst[1]), "--host", "127.0.0.1",
             "--port", str(PORT), "-c", "8192", "--jinja"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    deadline = time.time() + wait_seconds
    while time.time() < deadline:
        if server_running():
            return True
        if _proc.poll() is not None:
            return False  # crashed
        time.sleep(1)
    return False


def start_running_async() -> dict:
    """Kick off ensure_running() in a background thread and return immediately.

    Callers should poll status() — its "running" field reflects the real
    health check, and "starting"/"start_error" track the background attempt.
    """
    global _start_thread, _starting, _start_error
    if server_running():
        return {"ok": True, "already_running": True}
    binary = binary_path()
    inst = installed_model()
    if binary is None:
        return {"ok": False, "detail": "binary missing"}
    if inst is None:
        return {"ok": False, "detail": "model not downloaded"}

    with _start_lock:
        if _start_thread and _start_thread.is_alive():
            return {"ok": True, "starting": True}

        _starting = True
        _start_error = None

        def _run() -> None:
            global _starting, _start_error
            try:
                ok = ensure_running()
                if not ok:
                    _start_error = "failed to start"
            finally:
                _starting = False

        _start_thread = threading.Thread(target=_run, daemon=True)
        _start_thread.start()
    return {"ok": True, "starting": True}


def stop() -> bool:
    global _proc
    if _proc is not None and _proc.poll() is None:
        _proc.terminate()
        try:
            _proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            _proc.kill()
    _proc = None
    return True


# ── OpenAI-format chat translation ────────────────────────────────

def to_openai_messages(messages: list) -> list[dict]:
    """Our ChatMessage list → OpenAI chat format."""
    out: list[dict] = []
    for m in messages:
        entry: dict = {"role": m.role, "content": m.content or ""}
        if m.tool_calls:
            entry["tool_calls"] = [
                {"id": tc.id or f"call_{i}", "type": "function",
                 "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)}}
                for i, tc in enumerate(m.tool_calls)
            ]
        if m.tool_call_id:
            entry["tool_call_id"] = m.tool_call_id
        out.append(entry)
    return out


def from_openai_response(data: dict) -> dict:
    """OpenAI chat completion → Ollama-shaped raw dict (so the existing
    _parse_message in ollama.py handles it unchanged)."""
    choice = (data.get("choices") or [{}])[0]
    msg = choice.get("message") or {}
    usage = data.get("usage") or {}
    return {
        "message": {
            "role": msg.get("role", "assistant"),
            "content": msg.get("content") or "",
            "tool_calls": msg.get("tool_calls") or [],
        },
        "model": data.get("model", "local"),
        "total_duration": 0,
        "prompt_eval_count": usage.get("prompt_tokens", 0),
        "eval_count": usage.get("completion_tokens", 0),
        "done_reason": choice.get("finish_reason", "stop"),
    }
