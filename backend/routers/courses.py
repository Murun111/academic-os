"""Courses & Assignments API — /api/courses/*."""
from __future__ import annotations

from typing import Literal, Optional

import re
from datetime import date

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from backend.services.courses import Assignment, Course, CoursesService
from backend.services.learning_ai import LearningAIBadOutput, LearningAIUnavailable
from backend.services.syllabus_ai import extract_syllabus
from backend.services.text_extract import MAX_INPUT_BYTES, MAX_OUTPUT_CHARS, extract_text

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
    credits: Optional[float] = Field(None, ge=0, le=30)
    archived: Optional[bool] = None


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


# === syllabus import (literal paths: must be registered before /{course_id}) ===


class SyllabusItem(BaseModel):
    title: str
    due: Optional[str] = None
    weight: Optional[float] = None  # percent of grade; out-of-range is dropped with a warning
    points: Optional[float] = Field(None, ge=0)
    kind: str = ""


class SyllabusNewCourse(BaseModel):
    name: str = Field(..., min_length=1)
    term: str = Field(..., min_length=1)


class SyllabusApply(BaseModel):
    course_id: Optional[str] = None
    new_course: Optional[SyllabusNewCourse] = None
    items: list[SyllabusItem] = Field(default_factory=list, max_length=500)


def _norm_title(t: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", t.lower()).strip()


@router.post("/syllabus/preview")
async def syllabus_preview(
    file: Optional[UploadFile] = File(None),
    text: Optional[str] = Form(None),
    term_start: Optional[str] = Form(None),
    term_year: Optional[int] = Form(None),
):
    if file is not None and file.filename:
        data = await file.read(MAX_INPUT_BYTES + 1)
        if len(data) > MAX_INPUT_BYTES:
            raise HTTPException(status_code=413, detail="file too large (max 25 MB)")
        try:
            body = await run_in_threadpool(extract_text, data, file.filename)
        except ValueError as e:
            msg = str(e)
            if "too large" in msg:
                raise HTTPException(status_code=413, detail=msg)
            if "unsupported" in msg:
                raise HTTPException(status_code=415, detail=msg)
            raise HTTPException(status_code=422, detail=msg)
    elif text is not None:
        body = text.strip()
        if len(body) > MAX_OUTPUT_CHARS:
            raise HTTPException(
                status_code=413,
                detail=f"pasted text too long (max {MAX_OUTPUT_CHARS:,} characters)",
            )
    else:
        raise HTTPException(status_code=422, detail="provide a file or text")
    if not body.strip():
        raise HTTPException(
            status_code=422,
            detail="the file had no readable text (a scanned PDF needs OCR first)",
        )
    try:
        result = await extract_syllabus(body, term_start=term_start, term_year=term_year)
    except LearningAIUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e))
    except LearningAIBadOutput as e:
        raise HTTPException(status_code=502, detail=str(e))
    return {**result, "text_chars": len(body)}


@router.post("/syllabus/apply")
def syllabus_apply(body: SyllabusApply):
    svc = get_service()
    if bool(body.course_id) == bool(body.new_course):
        raise HTTPException(status_code=422, detail="provide exactly one of course_id or new_course")
    # validate everything before writing anything
    clean: list[tuple[str, Optional[str], Optional[float], Optional[float], str]] = []
    warnings: list[str] = []
    bad_weights = 0
    for i, it in enumerate(body.items):
        title = it.title.strip()
        if not title:
            raise HTTPException(status_code=422, detail=f"items[{i}]: title is empty")
        due = it.due.strip() if it.due else None
        if due:
            try:
                due = date.fromisoformat(due).isoformat()
            except ValueError:
                raise HTTPException(status_code=422, detail=f"items[{i}]: due must be YYYY-MM-DD")
        weight = None
        if it.weight is not None:
            if 0 <= it.weight <= 100:
                weight = it.weight / 100.0  # stored as a 0-1 fraction
            else:
                bad_weights += 1
        clean.append((title, due or None, weight, it.points, it.kind.strip()))
    if bad_weights:
        warnings.append(
            f"{bad_weights} weight(s) outside 0-100% were ignored (points are not percentages).")
    if body.course_id:
        course = next((c for c in svc.list_courses() if c.id == body.course_id), None)
        if course is None:
            raise HTTPException(status_code=404, detail=f"course {body.course_id!r} not found")
    else:
        try:
            course = svc.add_course(name=body.new_course.name, term=body.new_course.term)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))
    # multiset of existing (title, due): each incoming item consumes one match, so
    # re-imports skip duplicates but repeated undated items ("Reading reflection" x3) all land.
    seen: dict[tuple[str, Optional[str]], int] = {}
    for a in svc.list_assignments(course_id=course.id):
        k = (_norm_title(a.title), a.due)
        seen[k] = seen.get(k, 0) + 1
    created = skipped = 0
    for title, due, weight, points, kind in clean:
        key = (_norm_title(title), due)
        if seen.get(key, 0) > 0:
            if not due:  # undated: each existing copy absorbs one incoming item
                seen[key] -= 1
            skipped += 1
            continue
        note = f"Imported from syllabus ({kind})" if kind and kind != "other" else "Imported from syllabus"
        if points is not None:
            note += f", {points:g} pts"
        svc.add_assignment(
            course_id=course.id,
            title=title,
            due=due,
            weight=weight,
            notes=note,
        )
        created += 1
        if due:  # identical dated items inside one batch are duplicates
            seen[key] = 1
    return {"ok": True, "course": course.to_dict(), "created": created, "skipped": skipped, "warnings": warnings}


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
