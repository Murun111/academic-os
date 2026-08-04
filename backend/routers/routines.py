"""Routines router — deadline watcher + essay feedback, both on-demand."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from backend.services.routines import (
    deadline_digest,
    deadline_digest_llm,
    essay_feedback,
)

router = APIRouter(prefix="/api/routines", tags=["routines"])


class EssayFeedbackRequest(BaseModel):
    text: str = Field(..., min_length=1)
    prompt_hint: str = ""


class DeadlineBriefRequest(BaseModel):
    days: int = 14


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


@router.get("/catalog")
def get_catalog() -> dict:
    return CATALOG


@router.get("/deadline-digest")
def get_deadline_digest(days: int = 14) -> dict:
    return deadline_digest(days=days)


@router.post("/deadline-digest/brief")
async def post_deadline_digest_brief(request: Request, body: DeadlineBriefRequest) -> Any:
    ollama = request.app.state.ollama
    try:
        return await deadline_digest_llm(ollama, days=body.days)
    except Exception:
        return JSONResponse(status_code=503, content={"detail": "Local model offline — start Ollama"})


@router.post("/essay-feedback")
async def post_essay_feedback(request: Request, body: EssayFeedbackRequest) -> Any:
    ollama = request.app.state.ollama
    try:
        return await essay_feedback(ollama, text=body.text, prompt_hint=body.prompt_hint)
    except Exception:
        return JSONResponse(status_code=503, content={"detail": "Local model offline — start Ollama"})
