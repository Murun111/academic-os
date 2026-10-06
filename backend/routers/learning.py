"""Learning Hub router — /api/learning/*."""
from __future__ import annotations

from typing import Any, List, Optional

from fastapi import APIRouter, HTTPException, Query
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
