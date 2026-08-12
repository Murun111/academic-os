"""Courses & Assignments API — /api/courses/*."""
from __future__ import annotations

from typing import Literal, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from backend.services.courses import Assignment, Course, CoursesService

router = APIRouter(prefix="/api/courses", tags=["courses"])

_service: CoursesService | None = None


def get_service() -> CoursesService:
    global _service
    if _service is None:
        from backend.vault import agentic_os_dir

        _service = CoursesService(data_dir=agentic_os_dir() / "data" / "courses")
    return _service


def reset_service() -> None:  # for tests
    global _service
    _service = None


# === request bodies ===


class CourseCreate(BaseModel):
    name: str = Field(..., min_length=1)
    term: str = Field(..., min_length=1)
    instructor: str = ""


class CourseUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1)
    term: Optional[str] = Field(None, min_length=1)
    instructor: Optional[str] = None


class AssignmentCreate(BaseModel):
    course_id: str
    title: str = Field(..., min_length=1)
    due: Optional[str] = None
    status: Literal["todo", "done"] = "todo"
    grade: Optional[float] = Field(None, ge=0, le=100)
    weight: Optional[float] = Field(None, ge=0, le=1)
    notes: str = ""


class AssignmentUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=1)
    due: Optional[str] = None
    status: Optional[Literal["todo", "done"]] = None
    grade: Optional[float] = Field(None, ge=0, le=100)
    weight: Optional[float] = Field(None, ge=0, le=1)
    notes: Optional[str] = None


def _course_summary(svc: CoursesService, course: Course) -> dict:
    d = course.to_dict()
    # Canvas's own course total wins when synced; else average the assignments
    d["grade"] = course.canvas_score if course.canvas_score is not None else svc.course_grade(course.id)
    d["open_assignments"] = len(
        svc.list_assignments(course_id=course.id, status="todo")
    )
    return d


# === summary (must be registered before /{course_id}) ===


@router.get("/summary")
def get_summary():
    svc = get_service()
    courses = [_course_summary(svc, c) for c in svc.list_courses()]
    due_soon = [a.to_dict() for a in svc.due_soon()]
    return {"courses": courses, "due_soon": due_soon}


# === assignments (must be registered before /{course_id}) ===


@router.get("/assignments")
def list_assignments(
    course_id: Optional[str] = Query(None), status: Optional[str] = Query(None)
):
    svc = get_service()
    try:
        items = svc.list_assignments(course_id=course_id, status=status)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return {"assignments": [a.to_dict() for a in items], "count": len(items)}


@router.post("/assignments")
def add_assignment(body: AssignmentCreate):
    svc = get_service()
    try:
        assignment = svc.add_assignment(**body.model_dump())
    except KeyError:
        raise HTTPException(status_code=404, detail=f"course {body.course_id!r} not found")
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return {"ok": True, "assignment": assignment.to_dict()}


@router.patch("/assignments/{assignment_id}")
def update_assignment(assignment_id: str, body: AssignmentUpdate):
    svc = get_service()
    fields = body.model_dump(exclude_unset=True)
    try:
        assignment = svc.update_assignment(assignment_id, **fields)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"assignment {assignment_id!r} not found")
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return {"ok": True, "assignment": assignment.to_dict()}


@router.delete("/assignments/{assignment_id}")
def delete_assignment(assignment_id: str):
    svc = get_service()
    try:
        svc.delete_assignment(assignment_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"assignment {assignment_id!r} not found")
    return {"ok": True}


# === courses ===


@router.get("")
def list_courses():
    svc = get_service()
    courses = svc.list_courses()
    return {"courses": [c.to_dict() for c in courses], "count": len(courses)}


@router.post("")
def add_course(body: CourseCreate):
    svc = get_service()
    try:
        course = svc.add_course(**body.model_dump())
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return {"ok": True, "course": course.to_dict()}


@router.patch("/{course_id}")
def update_course(course_id: str, body: CourseUpdate):
    svc = get_service()
    fields = body.model_dump(exclude_unset=True)
    try:
        course = svc.update_course(course_id, **fields)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"course {course_id!r} not found")
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return {"ok": True, "course": course.to_dict()}


@router.delete("/{course_id}")
def delete_course(course_id: str):
    svc = get_service()
    try:
        svc.delete_course(course_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"course {course_id!r} not found")
    return {"ok": True}
