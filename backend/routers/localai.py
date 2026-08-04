"""Bundled local AI endpoints — status, model download, server lifecycle."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from backend.services import local_llm

router = APIRouter(prefix="/api/localai", tags=["localai"])


class DownloadBody(BaseModel):
    model: Literal["standard", "small"] = "standard"


@router.get("/status")
def localai_status() -> dict:
    """Binary/model/download/server state for the Local AI panel."""
    return local_llm.status()


@router.post("/download")
def localai_download(body: DownloadBody) -> JSONResponse:
    """Start (or resume) downloading a model in the background."""
    result = local_llm.download_model(body.model)
    code = 200 if result.get("ok") else 409 if result.get("error") == "download_in_progress" else 400
    return JSONResponse(result, status_code=code)


@router.post("/start")
def localai_start() -> JSONResponse:
    """Boot the llama-server (blocks until healthy or timeout)."""
    ok = local_llm.ensure_running()
    if ok:
        return JSONResponse({"ok": True, "running": True})
    s = local_llm.status()
    detail = ("model not downloaded" if not s["model"]
              else "binary missing" if not s["binary"] else "failed to start")
    return JSONResponse({"ok": False, "detail": detail}, status_code=503)


@router.post("/stop")
def localai_stop() -> dict:
    local_llm.stop()
    return {"ok": True, "running": False}
