"""Routines router — deadline watcher + essay feedback, both on-demand."""
from __future__ import annotations

from typing import Any

import httpx

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from backend.services.routines import (
    deadline_digest,
    deadline_digest_llm,
    essay_feedback,
    resume_feedback,
)

router = APIRouter(prefix="/api/routines", tags=["routines"])


class EssayFeedbackRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=60_000)
    prompt_hint: str = Field("", max_length=2_000)


class ResumeFeedbackRequest(BaseModel):
    content: str = Field(..., min_length=1, max_length=60_000)
    title: str = Field("", max_length=2_000)


class DeadlineBriefRequest(BaseModel):
    days: int = Field(14, ge=1, le=90)


CATALOG: dict = {
    "routines": [
        {
            "id": "deadline-watcher",
            "name": "Deadline Watcher",
            "description": (
                "Merges upcoming application deadlines and assignment due "
                "dates into one digest, with an optional AI briefing."
            ),
            "kind": "on_demand",
        },
        {
            "id": "essay-feedback",
            "name": "Essay Feedback",
            "description": (
                "Admissions-essay coach: structure, specificity, voice, and "
                "cliche feedback on demand."
            ),
            "kind": "on_demand",
        },
    ]
}


def _llm_failure(exc: Exception) -> JSONResponse:
    """503 only when the model is genuinely unreachable; anything else is a 502."""
    if isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout)):
        return JSONResponse(status_code=503, content={"detail": "Local model offline — start Ollama"})
    print(f"[routines] model call failed: {exc!r}")
    return JSONResponse(
        status_code=502,
        content={"detail": f"The local model failed to answer: {str(exc)[:200] or type(exc).__name__}"},
    )


@router.get("/catalog")
def get_catalog() -> dict:
    return CATALOG


@router.get("/deadline-digest")
def get_deadline_digest(days: int = Query(14, ge=1, le=90)) -> dict:
    return deadline_digest(days=days)


@router.post("/deadline-digest/brief")
async def post_deadline_digest_brief(request: Request, body: DeadlineBriefRequest) -> Any:
    ollama = request.app.state.ollama
    try:
        return await deadline_digest_llm(ollama, days=body.days)
    except Exception as e:
        return _llm_failure(e)


@router.post("/essay-feedback")
async def post_essay_feedback(request: Request, body: EssayFeedbackRequest) -> Any:
    ollama = request.app.state.ollama
    try:
        return await essay_feedback(ollama, text=body.text, prompt_hint=body.prompt_hint)
    except Exception as e:
        return _llm_failure(e)


@router.post("/resume-feedback")
async def post_resume_feedback(request: Request, body: ResumeFeedbackRequest) -> Any:
    ollama = request.app.state.ollama
    try:
        return await resume_feedback(ollama, content=body.content, title=body.title)
    except Exception as e:
        return _llm_failure(e)
