"""Study service — Task Planner's backend.

A local JSONL of study tasks the student wants to track: quick to-dos with
an optional planned day and/or due date, priority, and a done flag.

Same rationale as inbox.py: one JSONL file, atomic full-rewrite on update,
append-only on add. Crash-safe, git-trackable, `cat`-able.

This module also owns the cross-module `agenda` aggregation: it merges its
own tasks with upcoming application deadlines (backend.services.applications)
and upcoming assignments (backend.services.courses) into one date-sorted
feed. Those two services are built in parallel by other agents and may not
exist yet — every lookup into them is wrapped in try/except so the agenda
always returns at least this module's own tasks.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional


PRIORITIES = ("low", "normal", "high")


def _field(obj, name: str):
    """Best-effort attribute/key read — foreign objects may be dataclasses,
    plain objects, or dicts depending on how the other module implemented
    its return type."""
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


class StudyServiceError(Exception):
    """Raised when the study service can't complete an operation."""


@dataclass
class Task:
    id: str
    title: str
    created_at: str  # ISO 8601 datetime
    day: Optional[str] = None  # ISO 8601 date this task is planned for
    due: Optional[str] = None  # ISO 8601 date
    done: bool = False
    priority: str = "normal"
    notes: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Task":
        allowed = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in allowed})


class StudyService:
    """Local JSONL-backed task list.

    Adds append a line; updates/deletes rewrite the file (rare, fine for
    our scale).
    """

    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._path = self.data_dir / "tasks.jsonl"

    def _read_all(self) -> list[Task]:
        if not self._path.exists():
            return []
        tasks: list[Task] = []
        with self._path.open() as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                    tasks.append(Task.from_dict(d))
                except (json.JSONDecodeError, TypeError) as e:
                    print(f"[study] skipping malformed line: {e!r}")
                    continue
        return tasks

    def _write_all(self, tasks: list[Task]) -> None:
        """Atomic rewrite — write to .tmp, rename over the real file."""
        tmp = self._path.with_suffix(".jsonl.tmp")
        with tmp.open("w") as f:
            for t in tasks:
                f.write(json.dumps(t.to_dict(), separators=(",", ":")) + "\n")
        tmp.replace(self._path)

    def _new_id(self) -> str:
        return uuid.uuid4().hex[:12]

    def _now_iso(self) -> str:
        return datetime.now().isoformat(timespec="microseconds")

    def _validate_priority(self, p: str) -> str:
        p = (p or "normal").strip().lower()
        if p not in PRIORITIES:
            raise StudyServiceError(
                f"invalid priority {p!r}. Must be one of: {', '.join(PRIORITIES)}"
            )
        return p

    def _validate_title(self, title: str) -> str:
        title = (title or "").strip()
        if not title:
            raise StudyServiceError("title is required and cannot be empty")
        return title

    def _validate_date_str(self, value, field_name: str) -> Optional[str]:
        """Accept a date/datetime, an ISO date string, or None."""
        if value is None:
            return None
        if isinstance(value, str):
            try:
                date.fromisoformat(value)
            except ValueError:
                raise StudyServiceError(f"{field_name} must be an ISO date string")
            return value
        if isinstance(value, date):
            return value.isoformat()
        raise StudyServiceError(f"{field_name} must be a date, ISO date string, or None")

    # === CRUD ===

    def list_all(
        self, day: Optional[str] = None, done: Optional[bool] = None
    ) -> list[Task]:
        """Return all tasks, optionally filtered by day and/or done.

        Sorted by day (tasks without a day last), then created_at.
        """
        tasks = self._read_all()
        if day is not None:
            tasks = [t for t in tasks if t.day == day]
        if done is not None:
            tasks = [t for t in tasks if t.done == done]
        tasks.sort(key=lambda t: (t.day is None, t.day or "", t.created_at))
        return tasks

    def get(self, task_id: str) -> Task:
        for t in self._read_all():
            if t.id == task_id:
                return t
        raise StudyServiceError(f"task {task_id!r} not found")

    def add(self, **fields) -> Task:
        title = self._validate_title(fields.get("title"))
        priority = self._validate_priority(fields.get("priority", "normal"))
        day = self._validate_date_str(fields.get("day"), "day")
        due = self._validate_date_str(fields.get("due"), "due")
        done = bool(fields.get("done", False))
        notes = fields.get("notes") or ""
        task = Task(
            id=self._new_id(),
            title=title,
            created_at=self._now_iso(),
            day=day,
            due=due,
            done=done,
            priority=priority,
            notes=notes,
        )
        with self._path.open("a") as f:
            f.write(json.dumps(task.to_dict(), separators=(",", ":")) + "\n")
        return task

    def update(self, task_id: str, **fields) -> Task:
        if not fields:
            raise StudyServiceError("update() called with no fields to change")
        tasks = self._read_all()
        for t in tasks:
            if t.id == task_id:
                if "title" in fields and fields["title"] is not None:
                    t.title = self._validate_title(fields["title"])
                if "priority" in fields and fields["priority"] is not None:
                    t.priority = self._validate_priority(fields["priority"])
                if "day" in fields:
                    t.day = self._validate_date_str(fields["day"], "day")
                if "due" in fields:
                    t.due = self._validate_date_str(fields["due"], "due")
                if "done" in fields and fields["done"] is not None:
                    t.done = bool(fields["done"])
                if "notes" in fields and fields["notes"] is not None:
                    t.notes = fields["notes"]
                self._write_all(tasks)
                return t
        raise StudyServiceError(f"task {task_id!r} not found")

    def delete(self, task_id: str) -> None:
        tasks = self._read_all()
        new_tasks = [t for t in tasks if t.id != task_id]
        if len(new_tasks) == len(tasks):
            raise StudyServiceError(f"task {task_id!r} not found")
        self._write_all(new_tasks)

    def mark_done(self, task_id: str) -> Task:
        return self.update(task_id, done=True)

    def reopen(self, task_id: str) -> Task:
        return self.update(task_id, done=False)

    # === Cross-module aggregation ===

    def agenda(self, days: int = 7) -> dict:
        """Merged, date-sorted agenda across tasks, applications, and
        course assignments.

        Foreign-service lookups (applications, courses) are best-effort:
        any failure (import error, missing method, exception at call time)
        is swallowed so the agenda always returns at least this module's
        own tasks.
        """
        today = date.today()
        window_end = today + timedelta(days=days)

        items: list[dict] = []

        for t in self._read_all():
            candidate_dates = [d for d in (t.day, t.due) if d]
            in_window = False
            for d in candidate_dates:
                try:
                    parsed = date.fromisoformat(d)
                except ValueError:
                    continue
                if parsed <= window_end:
                    in_window = True
            if not candidate_dates or not in_window:
                continue
            sort_date = t.day or t.due
            items.append(
                {
                    "kind": "task",
                    "id": t.id,
                    "title": t.title,
                    "date": sort_date,
                    "meta": {"priority": t.priority, "day": t.day, "due": t.due,
                             "done": t.done},
                }
            )

        items.extend(self._applications_items(days))
        items.extend(self._assignments_items(days))

        items.sort(key=lambda i: (i["date"] or "", i["kind"]))
        return {"items": items, "count": len(items)}

    def _applications_items(self, days: int) -> list[dict]:
        try:
            from backend.services.applications import ApplicationsService
            from backend.vault import agentic_os_dir

            service = ApplicationsService(
                data_dir=agentic_os_dir() / "data" / "applications"
            )
            deadlines = service.upcoming_deadlines(days)
        except Exception:
            return []

        out: list[dict] = []
        try:
            for d in deadlines:
                out.append(
                    {
                        "kind": "application",
                        "id": _field(d, "id"),
                        "title": _field(d, "title"),
                        "date": _field(d, "date"),
                        "meta": {
                            "type": _field(d, "type"),
                            "status": _field(d, "status"),
                        },
                    }
                )
        except Exception:
            return []
        return out

    def _assignments_items(self, days: int) -> list[dict]:
        try:
            from backend.services.courses import CoursesService
            from backend.vault import agentic_os_dir

            service = CoursesService(data_dir=agentic_os_dir() / "data" / "courses")
            assignments = service.due_soon(days)
        except Exception:
            return []

        out: list[dict] = []
        try:
            for a in assignments:
                out.append(
                    {
                        "kind": "assignment",
                        "id": _field(a, "id"),
                        "title": _field(a, "title"),
                        "date": _field(a, "date"),
                        "meta": {
                            "course_id": _field(a, "course_id"),
                            "status": _field(a, "status"),
                        },
                    }
                )
        except Exception:
            return []
        return out
