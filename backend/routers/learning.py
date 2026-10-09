"""Learning Hub router — /api/learning/*."""
from __future__ import annotations

import uuid
from typing import Any, List, Optional

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from backend.services.learning import (
    LearningService,
    LearningServiceError,
)
from backend.services.learning_ai import (
    LearningAIBadOutput,
    LearningAIUnavailable,
    generate_flashcards_ai,
    generate_quiz_ai,
    generate_study_guide_ai,
    socratic_tutor_response,
)
from backend.services import deck_import
from backend.services.srs_engine import Rating

router = APIRouter(prefix="/api/learning", tags=["learning"])

_service: LearningService | None = None


def get_service() -> LearningService:
    global _service
    if _service is None:
        from backend.vault import agentic_os_dir

        _service = LearningService(data_dir=agentic_os_dir() / "data" / "learning")
    return _service


def reset_service() -> None:
    global _service
    _service = None


# ── Pydantic Request Models ──────────────────────────────────────────
class DeckCreate(BaseModel):
    title: str
    description: str = ""
    course_id: Optional[str] = None
    course_name: Optional[str] = None
    tags: list[str] = Field(default_factory=list)
    cards: list[dict[str, Any]] = Field(default_factory=list)


class DeckUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    course_id: Optional[str] = None
    course_name: Optional[str] = None
    tags: Optional[list[str]] = None


class CardCreate(BaseModel):
    front: str
    back: str
    hint: str = ""
    explanation: str = ""
    tags: list[str] = Field(default_factory=list)


class CardReviewRequest(BaseModel):
    rating: Rating


class QuizCreate(BaseModel):
    title: str
    topic: str
    course_id: Optional[str] = None
    course_name: Optional[str] = None
    time_limit_mins: int = 15
    questions: list[dict[str, Any]] = Field(default_factory=list)


class QuizSubmitRequest(BaseModel):
    answers: dict[str, Any]
    time_spent_secs: int = 0


class TopicCreate(BaseModel):
    name: str
    course_id: Optional[str] = None
    course_name: Optional[str] = None
    status: str = "developing"


class TopicUpdate(BaseModel):
    status: str


class GuideCreate(BaseModel):
    title: str
    topic: str
    content: str
    course_id: Optional[str] = None
    course_name: Optional[str] = None
    key_takeaways: list[str] = Field(default_factory=list)
    formulas: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)


class FocusSessionCreate(BaseModel):
    duration_minutes: int
    topic: str
    goal: str = ""
    reflections: str = ""
    course_id: Optional[str] = None
    course_name: Optional[str] = None


class GenerateFlashcardsRequest(BaseModel):
    topic: str
    context_text: str = ""
    count: int = 5
    difficulty: str = "medium"
    save_to_deck: bool = False
    deck_title: Optional[str] = None
    course_id: Optional[str] = None
    course_name: Optional[str] = None


class GenerateQuizRequest(BaseModel):
    topic: str
    context_text: str = ""
    num_questions: int = 4
    difficulty: str = "medium"
    save_as_quiz: bool = False
    quiz_title: Optional[str] = None
    course_id: Optional[str] = None
    course_name: Optional[str] = None


class GenerateGuideRequest(BaseModel):
    topic: str
    context_text: str = ""
    save_as_guide: bool = False
    course_id: Optional[str] = None
    course_name: Optional[str] = None


class SocraticTutorRequest(BaseModel):
    topic: str
    messages: list[dict[str, str]]
    context: str = ""


# ── Endpoints ────────────────────────────────────────────────────────
@router.get("/overview")
def get_overview() -> dict[str, Any]:
    return get_service().get_overview()


# ── Deck import (literal paths: must register before /decks/{deck_id}) ──
MAX_IMPORT_BYTES = deck_import.MAX_ZIP_BYTES  # test override
_IMPORT_CHUNK = 1024 * 1024
_IMPORT_FORMATS = {"auto", "apkg", "quizlet", "delimited"}
_PREVIEW_CARDS = 20


async def _read_import(
    file: UploadFile | None,
    text: str | None,
    fmt: str,
    term_sep: str,
    row_sep: str,
) -> "deck_import.ImportResult":
    if fmt not in _IMPORT_FORMATS:
        raise HTTPException(status_code=422, detail=f"Unknown format '{fmt}'")
    limit = MAX_IMPORT_BYTES
    data: bytes | None = None
    filename = ""
    if file is not None and (file.filename or "") != "":
        filename = (file.filename or "").lower()
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = await file.read(_IMPORT_CHUNK)
            if not chunk:
                break
            total += len(chunk)
            if total > limit:
                await file.close()
                raise HTTPException(
                    status_code=413, detail=f"File too large (max {limit // (1024 * 1024)} MB)"
                )
            chunks.append(chunk)
        data = b"".join(chunks)
        if not data:
            data = None
    if data is None:
        if text is None or not text.strip():
            raise HTTPException(status_code=422, detail="Provide a file or pasted text to import")
        if len(text.encode("utf-8")) > limit:
            raise HTTPException(
                status_code=413, detail=f"Text too large (max {limit // (1024 * 1024)} MB)"
            )

    is_zip = data is not None and data[:4] in (b"PK\x03\x04", b"PK\x05\x06")
    if fmt == "auto":
        if is_zip or filename.endswith((".apkg", ".colpkg")):
            fmt = "apkg"
        elif filename.endswith(".csv"):
            fmt = "delimited"
        else:
            body = (data.decode("utf-8-sig", errors="replace") if data is not None else text) or ""
            fmt = "delimited" if deck_import.looks_like_header(body) else "quizlet"

    try:
        if fmt == "apkg":
            if data is None:
                raise ValueError("The .apkg format needs a file upload")
            return await run_in_threadpool(deck_import.parse_apkg, data)
        body = data.decode("utf-8-sig", errors="replace") if data is not None else (text or "")
        if fmt == "delimited":
            return await run_in_threadpool(deck_import.parse_delimited, body)
        return await run_in_threadpool(deck_import.parse_quizlet_text, body, term_sep, row_sep)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.post("/import/preview")
async def import_preview(
    file: UploadFile | None = File(default=None),
    text: Optional[str] = Form(default=None),
    format: str = Form(default="auto"),
    term_sep: str = Form(default="auto"),
    row_sep: str = Form(default="auto"),
) -> dict[str, Any]:
    res = await _read_import(file, text, format, term_sep, row_sep)
    return {
        "cards": res.cards[:_PREVIEW_CARDS],
        "total": len(res.cards),
        "warnings": res.warnings,
        "skipped": res.skipped,
    }


@router.post("/import")
async def import_deck(
    deck_title: str = Form(...),
    file: UploadFile | None = File(default=None),
    text: Optional[str] = Form(default=None),
    format: str = Form(default="auto"),
    term_sep: str = Form(default="auto"),
    row_sep: str = Form(default="auto"),
    course_id: Optional[str] = Form(default=None),
    course_name: Optional[str] = Form(default=None),
) -> dict[str, Any]:
    if not deck_title.strip():
        raise HTTPException(status_code=422, detail="deck_title is required")
    res = await _read_import(file, text, format, term_sep, row_sep)
    if not res.cards:
        raise HTTPException(status_code=422, detail="No importable cards were found")
    try:
        # full-length ids: the service's default 8-hex ids collide at large sizes
        deck = await run_in_threadpool(
            get_service().create_deck,
            title=deck_title,
            course_id=course_id or None,
            course_name=course_name or None,
            cards=[
                {
                    "id": f"card_{uuid.uuid4().hex}",
                    "front": c["front"],
                    "back": c["back"],
                    "tags": c.get("tags", []),
                }
                for c in res.cards
            ],
        )
    except LearningServiceError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return {
        "deck": deck,
        "imported": len(res.cards),
        "warnings": res.warnings,
        "skipped": res.skipped,
    }


# ── Decks & Flashcards ────────────────────────────────────────────────
@router.get("/decks")
def list_decks(course_id: Optional[str] = Query(default=None)) -> list[dict[str, Any]]:
    return get_service().list_decks(course_id=course_id)


@router.post("/decks")
def create_deck(body: DeckCreate) -> dict[str, Any]:
    try:
        return get_service().create_deck(**body.model_dump())
    except LearningServiceError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.get("/decks/{deck_id}")
def get_deck(deck_id: str) -> dict[str, Any]:
    try:
        return get_service().get_deck(deck_id)
    except LearningServiceError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.patch("/decks/{deck_id}")
def update_deck(deck_id: str, body: DeckUpdate) -> dict[str, Any]:
    try:
        return get_service().update_deck(deck_id, **body.model_dump(exclude_unset=True))
    except LearningServiceError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/decks/{deck_id}")
def delete_deck(deck_id: str) -> dict[str, Any]:
    try:
        get_service().delete_deck(deck_id)
        return {"ok": True}
    except LearningServiceError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/decks/{deck_id}/cards")
def add_card(deck_id: str, body: CardCreate) -> dict[str, Any]:
    try:
        return get_service().add_card(deck_id, **body.model_dump())
    except LearningServiceError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/decks/{deck_id}/cards/{card_id}")
def delete_card(deck_id: str, card_id: str) -> dict[str, Any]:
    try:
        get_service().delete_card(deck_id, card_id)
        return {"ok": True}
    except LearningServiceError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/due-cards")
def get_due_cards(deck_id: Optional[str] = Query(default=None)) -> list[dict[str, Any]]:
    return get_service().get_due_cards(deck_id=deck_id)


@router.post("/decks/{deck_id}/cards/{card_id}/review")
def review_card(deck_id: str, card_id: str, body: CardReviewRequest) -> dict[str, Any]:
    try:
        return get_service().submit_card_review(deck_id, card_id, body.rating)
    except LearningServiceError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ── Quizzes ───────────────────────────────────────────────────────────
@router.get("/quizzes")
def list_quizzes(course_id: Optional[str] = Query(default=None)) -> list[dict[str, Any]]:
    return get_service().list_quizzes(course_id=course_id)


@router.post("/quizzes")
def create_quiz(body: QuizCreate) -> dict[str, Any]:
    try:
        return get_service().create_quiz(**body.model_dump())
    except LearningServiceError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.get("/quizzes/{quiz_id}")
def get_quiz(quiz_id: str) -> dict[str, Any]:
    try:
        return get_service().get_quiz(quiz_id)
    except LearningServiceError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/quizzes/{quiz_id}")
def delete_quiz(quiz_id: str) -> dict[str, Any]:
    try:
        get_service().delete_quiz(quiz_id)
        return {"ok": True}
    except LearningServiceError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/quizzes/{quiz_id}/submit")
def submit_quiz(quiz_id: str, body: QuizSubmitRequest) -> dict[str, Any]:
    try:
        return get_service().submit_quiz_attempt(
            quiz_id=quiz_id,
            answers=body.answers,
            time_spent_secs=body.time_spent_secs,
        )
    except LearningServiceError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ── Mastery Matrix ───────────────────────────────────────────────────
@router.get("/mastery")
def get_mastery() -> dict[str, Any]:
    return get_service().get_mastery_matrix()


@router.post("/mastery/topics")
def add_topic(body: TopicCreate) -> dict[str, Any]:
    try:
        return get_service().add_topic(**body.model_dump())
    except LearningServiceError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.patch("/mastery/topics/{topic_id}")
def update_topic(topic_id: str, body: TopicUpdate) -> dict[str, Any]:
    try:
        return get_service().set_topic_status(topic_id, body.status)
    except LearningServiceError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ── Study Guides ──────────────────────────────────────────────────────
@router.get("/guides")
def list_guides(course_id: Optional[str] = Query(default=None)) -> list[dict[str, Any]]:
    return get_service().list_guides(course_id=course_id)


@router.post("/guides")
def create_guide(body: GuideCreate) -> dict[str, Any]:
    try:
        return get_service().create_guide(**body.model_dump())
    except LearningServiceError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.get("/guides/{guide_id}")
def get_guide(guide_id: str) -> dict[str, Any]:
    try:
        return get_service().get_guide(guide_id)
    except LearningServiceError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/guides/{guide_id}")
def delete_guide(guide_id: str) -> dict[str, Any]:
    try:
        get_service().delete_guide(guide_id)
        return {"ok": True}
    except LearningServiceError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ── Focus Sessions ────────────────────────────────────────────────────
@router.get("/focus")
def list_focus() -> list[dict[str, Any]]:
    return get_service().list_focus_sessions()


@router.post("/focus")
def log_focus(body: FocusSessionCreate) -> dict[str, Any]:
    try:
        return get_service().log_focus_session(**body.model_dump())
    except LearningServiceError as e:
        raise HTTPException(status_code=422, detail=str(e))


# ── AI Generation & Tutor ─────────────────────────────────────────────
async def _ai(coro):
    try:
        return await coro
    except LearningAIUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e))
    except LearningAIBadOutput as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.post("/generate/flashcards")
async def generate_flashcards(body: GenerateFlashcardsRequest) -> dict[str, Any]:
    cards = await _ai(generate_flashcards_ai(
        topic=body.topic,
        context_text=body.context_text,
        count=body.count,
        difficulty=body.difficulty,
    ))
    deck = None
    if body.save_to_deck:
        deck_title = body.deck_title or f"{body.topic} Flashcards"
        deck = get_service().create_deck(
            title=deck_title,
            description=f"AI-generated study deck for {body.topic}",
            course_id=body.course_id,
            course_name=body.course_name,
            tags=[body.topic, "AI-Generated"],
            cards=cards,
        )
    return {"cards": cards, "deck": deck}


@router.post("/generate/quiz")
async def generate_quiz(body: GenerateQuizRequest) -> dict[str, Any]:
    questions = await _ai(generate_quiz_ai(
        topic=body.topic,
        context_text=body.context_text,
        num_questions=body.num_questions,
        difficulty=body.difficulty,
    ))
    quiz = None
    if body.save_as_quiz:
        quiz_title = body.quiz_title or f"{body.topic} Practice Exam"
        quiz = get_service().create_quiz(
            title=quiz_title,
            topic=body.topic,
            course_id=body.course_id,
            course_name=body.course_name,
            questions=questions,
            time_limit_mins=body.num_questions * 3,
        )
    return {"questions": questions, "quiz": quiz}


@router.post("/generate/guide")
async def generate_guide(body: GenerateGuideRequest) -> dict[str, Any]:
    guide_data = await _ai(generate_study_guide_ai(
        topic=body.topic,
        context_text=body.context_text,
    ))
    guide = None
    if body.save_as_guide:
        guide = get_service().create_guide(
            title=guide_data.get("title", f"{body.topic} Study Guide"),
            topic=body.topic,
            content=guide_data.get("summary_markdown", ""),
            course_id=body.course_id,
            course_name=body.course_name,
            key_takeaways=guide_data.get("key_takeaways", []),
            formulas=guide_data.get("formulas", []),
            tags=guide_data.get("tags", []),
        )
    return {"guide_data": guide_data, "guide": guide}


@router.post("/tutor")
async def tutor_chat(body: SocraticTutorRequest) -> dict[str, Any]:
    reply = await _ai(socratic_tutor_response(
        topic=body.topic,
        messages=body.messages,
        context=body.context,
    ))
    return {"reply": reply}
