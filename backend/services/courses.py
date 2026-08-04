"""Courses & Assignments service — Academic OS.

Two JSONL ledgers under one data directory: courses.jsonl and
assignments.jsonl. Same storage discipline as inbox.py (append for
adds, atomic full rewrite for updates/deletes). IDs are short uuid4
hex strings, dates are ISO strings.

Deleting a course cascades: its assignments are removed too.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional


STATUSES = ("todo", "done")


@dataclass
class Course:
    id: str
    name: str
    term: str
    created_at: str
    instructor: str = ""
    source: str = ""       # "" = manual; "canvas" = synced from Canvas
    external_id: str = ""  # stable id from the source so re-syncs upsert

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Course":
        allowed = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in allowed})


@dataclass
class Assignment:
    id: str
    course_id: str
    title: str
    created_at: str
    due: Optional[str] = None
    status: str = "todo"
    grade: Optional[float] = None
    weight: Optional[float] = None
    notes: str = ""
    source: str = ""       # "" = manual; "ics" = synced from an LMS calendar feed
    external_id: str = ""  # stable id from the source (ICS UID) so re-syncs upsert

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Assignment":
        allowed = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in allowed})


class CoursesService:
    """Local JSONL-backed courses + assignments store."""

    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._courses_path = self.data_dir / "courses.jsonl"
        self._assignments_path = self.data_dir / "assignments.jsonl"

    # === low-level IO ===

    def _read_courses(self) -> list[Course]:
        return self._read_jsonl(self._courses_path, Course)

    def _read_assignments(self) -> list[Assignment]:
        return self._read_jsonl(self._assignments_path, Assignment)

    @staticmethod
    def _read_jsonl(path: Path, cls) -> list:
        if not path.exists():
            return []
        out = []
        with path.open() as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(cls.from_dict(json.loads(line)))
                except (json.JSONDecodeError, TypeError) as e:
                    print(f"[courses] skipping malformed line in {path.name}: {e!r}")
                    continue
        return out

    @staticmethod
    def _write_jsonl(path: Path, items: list) -> None:
        tmp = path.with_suffix(".jsonl.tmp")
        with tmp.open("w") as f:
            for it in items:
                f.write(json.dumps(it.to_dict(), separators=(",", ":")) + "\n")
        tmp.replace(path)

    def _write_courses(self, courses: list[Course]) -> None:
        self._write_jsonl(self._courses_path, courses)

    def _write_assignments(self, assignments: list[Assignment]) -> None:
        self._write_jsonl(self._assignments_path, assignments)

    def _append_course(self, course: Course) -> None:
        with self._courses_path.open("a") as f:
            f.write(json.dumps(course.to_dict(), separators=(",", ":")) + "\n")

    def _append_assignment(self, assignment: Assignment) -> None:
        with self._assignments_path.open("a") as f:
            f.write(json.dumps(assignment.to_dict(), separators=(",", ":")) + "\n")

    @staticmethod
    def _new_id() -> str:
        return uuid.uuid4().hex[:12]

    @staticmethod
    def _now_iso() -> str:
        return datetime.now().isoformat(timespec="microseconds")

    @staticmethod
    def _validate_status(status: str) -> str:
        if status not in STATUSES:
            raise ValueError(f"invalid status {status!r}. Must be one of: {', '.join(STATUSES)}")
        return status

    # === courses ===

    def list_courses(self) -> list[Course]:
        courses = self._read_courses()
        courses.sort(key=lambda c: c.created_at)
        return courses

    def add_course(self, **fields) -> Course:
        name = (fields.get("name") or "").strip()
        term = (fields.get("term") or "").strip()
        if not name:
            raise ValueError("name is required and cannot be empty")
        if not term:
            raise ValueError("term is required and cannot be empty")
        instructor = fields.get("instructor") or ""
        course = Course(
            id=self._new_id(),
            name=name,
            term=term,
            instructor=instructor,
            source=fields.get("source") or "",
            external_id=fields.get("external_id") or "",
            created_at=self._now_iso(),
        )
        self._append_course(course)
        return course

    def update_course(self, course_id: str, **fields) -> Course:
        courses = self._read_courses()
        for c in courses:
            if c.id == course_id:
                if "name" in fields and fields["name"] is not None:
                    name = str(fields["name"]).strip()
                    if not name:
                        raise ValueError("name cannot be empty")
                    c.name = name
                if "term" in fields and fields["term"] is not None:
                    term = str(fields["term"]).strip()
                    if not term:
                        raise ValueError("term cannot be empty")
                    c.term = term
                if "instructor" in fields and fields["instructor"] is not None:
                    c.instructor = fields["instructor"]
                self._write_courses(courses)
                return c
        raise KeyError(course_id)

    def delete_course(self, course_id: str) -> None:
        courses = self._read_courses()
        remaining = [c for c in courses if c.id != course_id]
        if len(remaining) == len(courses):
            raise KeyError(course_id)
        self._write_courses(remaining)
        # cascade: drop this course's assignments too
        assignments = self._read_assignments()
        kept = [a for a in assignments if a.course_id != course_id]
        if len(kept) != len(assignments):
            self._write_assignments(kept)

    def _course_exists(self, course_id: str) -> bool:
        return any(c.id == course_id for c in self._read_courses())

    # === assignments ===

    def list_assignments(
        self, course_id: Optional[str] = None, status: Optional[str] = None
    ) -> list[Assignment]:
        items = self._read_assignments()
        if course_id is not None:
            items = [a for a in items if a.course_id == course_id]
        if status is not None:
            status = self._validate_status(status)
            items = [a for a in items if a.status == status]
        items.sort(key=lambda a: a.created_at)
        return items

    def add_assignment(self, **fields) -> Assignment:
        course_id = fields.get("course_id")
        if not course_id or not self._course_exists(course_id):
            raise KeyError(course_id)
        title = (fields.get("title") or "").strip()
        if not title:
            raise ValueError("title is required and cannot be empty")
        status = self._validate_status(fields.get("status") or "todo")
        grade = fields.get("grade")
        weight = fields.get("weight")
        due = fields.get("due")
        notes = fields.get("notes") or ""
        assignment = Assignment(
            id=self._new_id(),
            course_id=course_id,
            title=title,
            due=due,
            status=status,
            grade=grade,
            weight=weight,
            notes=notes,
            source=fields.get("source") or "",
            external_id=fields.get("external_id") or "",
            created_at=self._now_iso(),
        )
        self._append_assignment(assignment)
        return assignment

    def update_assignment(self, assignment_id: str, **fields) -> Assignment:
        items = self._read_assignments()
        for a in items:
            if a.id == assignment_id:
                if "title" in fields and fields["title"] is not None:
                    title = str(fields["title"]).strip()
                    if not title:
                        raise ValueError("title cannot be empty")
                    a.title = title
                if "due" in fields:
                    a.due = fields["due"]
                if "status" in fields and fields["status"] is not None:
                    a.status = self._validate_status(fields["status"])
                if "grade" in fields:
                    a.grade = fields["grade"]
                if "weight" in fields:
                    a.weight = fields["weight"]
                if "notes" in fields and fields["notes"] is not None:
                    a.notes = fields["notes"]
                self._write_assignments(items)
                return a
        raise KeyError(assignment_id)

    def delete_assignment(self, assignment_id: str) -> None:
        items = self._read_assignments()
        remaining = [a for a in items if a.id != assignment_id]
        if len(remaining) == len(items):
            raise KeyError(assignment_id)
        self._write_assignments(remaining)

    # === aggregates ===

    def due_soon(self, days: int = 14) -> list[Assignment]:
        today = date.today()
        horizon = today + timedelta(days=days)
        items = []
        for a in self._read_assignments():
            if a.status != "todo" or not a.due:
                continue
            d = date.fromisoformat(a.due)
            if today <= d <= horizon:
                items.append(a)
        items.sort(key=lambda a: a.due)
        return items

    def course_grade(self, course_id: str) -> Optional[float]:
        graded = [
            a
            for a in self._read_assignments()
            if a.course_id == course_id and a.grade is not None
        ]
        if not graded:
            return None
        total_weight = sum(a.weight or 0 for a in graded)
        if total_weight <= 0:
            return sum(a.grade for a in graded) / len(graded)
        weighted_sum = sum(a.grade * (a.weight or 0) for a in graded)
        return weighted_sum / total_weight
