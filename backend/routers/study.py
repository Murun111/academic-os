"""Study / Task Planner router — /api/study/*."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, field_validator

from backend.services.study import PRIORITIES, StudyService, StudyServiceError

router = APIRouter(prefix="/api/study", tags=["study"])

_service: StudyService | None = None


def get_service() -> StudyService:
    global _service
    if _service is None:
        from backend.vault import agentic_os_dir

        _service = StudyService(data_dir=agentic_os_dir() / "data" / "study")
    return _service


def reset_service() -> None:  # for tests
    global _service
    _service = None


class TaskCreate(BaseModel):
    title: str
    day: Optional[str] = None
    due: Optional[str] = None
    priority: str = "normal"
    notes: str = ""

    @field_validator("priority")
    @classmethod
    def _valid_priority(cls, v: str) -> str:
        if v not in PRIORITIES:
            raise ValueError(f"priority must be one of: {', '.join(PRIORITIES)}")
        return v


class TaskUpdate(BaseModel):
    title: Optional[str] = None
    day: Optional[str] = None
    due: Optional[str] = None
    done: Optional[bool] = None
    priority: Optional[str] = None
    notes: Optional[str] = None

    @field_validator("priority")
    @classmethod
    def _valid_priority(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in PRIORITIES:
            raise ValueError(f"priority must be one of: {', '.join(PRIORITIES)}")
        return v


# NOTE: /agenda must be registered before /tasks/{task_id} routes so it
# doesn't get shadowed — kept as its own path segment, no collision, but
# order matches the contract's stated intent.


@router.get("/agenda")
def get_agenda(days: int = Query(default=7, ge=1, le=90)) -> dict:
    return get_service().agenda(days=days)


@router.get("/tasks")
def list_tasks(
    day: Optional[str] = Query(default=None),
    done: Optional[bool] = Query(default=None),
) -> list[dict]:
    try:
        tasks = get_service().list_all(day=day, done=done)
    except StudyServiceError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return [t.to_dict() for t in tasks]


@router.post("/tasks")
def create_task(body: TaskCreate) -> dict:
    try:
        task = get_service().add(**body.model_dump())
    except StudyServiceError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return task.to_dict()


@router.patch("/tasks/{task_id}")
def update_task(task_id: str, body: TaskUpdate) -> dict:
    fields = body.model_dump(exclude_unset=True)
    try:
        task = get_service().update(task_id, **fields)
    except StudyServiceError as e:
        msg = str(e)
        status = 404 if "not found" in msg else 422
        raise HTTPException(status_code=status, detail=msg)
    return task.to_dict()


@router.delete("/tasks/{task_id}")
def delete_task(task_id: str) -> dict:
    try:
        get_service().delete(task_id)
    except StudyServiceError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"ok": True}


@router.post("/tasks/{task_id}/done")
def mark_done(task_id: str) -> dict:
    try:
        task = get_service().mark_done(task_id)
    except StudyServiceError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return task.to_dict()


@router.post("/tasks/{task_id}/reopen")
def reopen_task(task_id: str) -> dict:
    try:
        task = get_service().reopen(task_id)
    except StudyServiceError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return task.to_dict()
