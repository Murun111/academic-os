"""Applications service — the flagship Applications Pipeline module.

Tracks university / scholarship / exchange applications as a local
JSONL ledger: one line per application, requirements checklist nested
inline. Mirrors backend/services/inbox.py: JSONL storage, atomic
rewrite on update, uuid4 hex ids, ISO date/datetime strings.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional


TYPES = ("undergrad", "grad", "scholarship", "exchange")
STATUSES = ("researching", "preparing", "submitted", "interview", "decision")
DECISION_RESULTS = ("", "accepted", "rejected", "waitlisted")


@dataclass
class Application:
    id: str
    name: str
    org: str = ""
    type: str = ""
    status: str = "researching"
    decision_result: str = ""
    deadline: Optional[str] = None  # ISO date
    url: str = ""
    notes: str = ""
    requirements: list = field(default_factory=list)  # [{id, label, done}]
    document_ids: list = field(default_factory=list)
    amount: Optional[float] = None  # scholarship/award amount in USD
    app_fee: Optional[float] = None  # application fee in USD
    fee_waived: bool = False
    archived: bool = False  # finished/abandoned — hidden from the board, kept for export
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Application":
        # Defensive: skip fields that aren't part of the schema.
        allowed = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in allowed})


class ApplicationsService:
    """Local JSONL-backed applications pipeline.

    One line per application; requirements are nested inline (small
    lists, no need for a separate file). Updates rewrite the file.
    """

    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._path = self.data_dir / "items.jsonl"

    # === internal I/O ===

    def _read_all(self) -> list[Application]:
        if not self._path.exists():
            return []
        items: list[Application] = []
        with self._path.open() as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                    items.append(Application.from_dict(d))
                except (json.JSONDecodeError, TypeError) as e:
                    # Skip malformed lines silently — same policy as inbox.
                    print(f"[applications] skipping malformed line: {e!r}")
                    continue
        return items

    def _write_all(self, items: list[Application]) -> None:
        """Atomic rewrite — write to .tmp, rename over the real file."""
        tmp = self._path.with_suffix(".jsonl.tmp")
        with tmp.open("w") as f:
            for it in items:
                f.write(json.dumps(it.to_dict(), separators=(",", ":")) + "\n")
        tmp.replace(self._path)

    def _new_id(self) -> str:
        return uuid.uuid4().hex[:12]

    def _now_iso(self) -> str:
        return datetime.now().isoformat(timespec="microseconds")

    # === validation ===

    def _validate_type(self, t: str) -> str:
        t = (t or "").strip().lower()
        if t not in TYPES:
            raise ValueError(f"invalid type {t!r}. Must be one of: {', '.join(TYPES)}")
        return t

    def _validate_status(self, s: str) -> str:
        s = (s or "").strip().lower()
        if s not in STATUSES:
            raise ValueError(f"invalid status {s!r}. Must be one of: {', '.join(STATUSES)}")
        return s

    def _validate_decision_result(self, r: str) -> str:
        r = (r or "").strip().lower()
        if r not in DECISION_RESULTS:
            raise ValueError(
                f"invalid decision_result {r!r}. Must be one of: {', '.join(DECISION_RESULTS)}"
            )
        return r

    def _validate_name(self, name: str) -> str:
        name = (name or "").strip()
        if not name:
            raise ValueError("name is required and cannot be empty")
        return name

    def _validate_amount(self, value, field_name: str) -> Optional[float]:
        if value is None:
            return None
        try:
            amount = float(value)
        except (TypeError, ValueError):
            raise ValueError(f"{field_name} must be a number")
        if amount < 0:
            raise ValueError(f"{field_name} must be >= 0")
        return amount

    def _normalize_requirement(self, r: dict) -> dict:
        return {
            "id": r.get("id") or self._new_id(),
            "label": str(r.get("label", "")).strip(),
            "done": bool(r.get("done", False)),
        }

    # === CRUD ===

    def list_all(self, type: Optional[str] = None, status: Optional[str] = None) -> list[Application]:
        """Return all applications, optionally filtered. Newest-first by created_at."""
        items = self._read_all()
        if type is not None:
            type = self._validate_type(type)
            items = [i for i in items if i.type == type]
        if status is not None:
            status = self._validate_status(status)
            items = [i for i in items if i.status == status]
        items.sort(key=lambda i: i.created_at, reverse=True)
        return items

    def get(self, app_id: str) -> Application:
        for i in self._read_all():
            if i.id == app_id:
                return i
        raise KeyError(app_id)

    def add(self, **fields) -> Application:
        name = self._validate_name(fields.get("name", ""))
        type_ = self._validate_type(fields.get("type", ""))
        status = self._validate_status(fields.get("status") or "researching")
        decision_result = self._validate_decision_result(fields.get("decision_result") or "")
        requirements = [self._normalize_requirement(r) for r in (fields.get("requirements") or [])]
        amount = self._validate_amount(fields.get("amount"), "amount")
        app_fee = self._validate_amount(fields.get("app_fee"), "app_fee")
        now = self._now_iso()
        item = Application(
            id=self._new_id(),
            name=name,
            org=fields.get("org") or "",
            type=type_,
            status=status,
            decision_result=decision_result,
            deadline=fields.get("deadline"),
            url=fields.get("url") or "",
            notes=fields.get("notes") or "",
            requirements=requirements,
            document_ids=list(fields.get("document_ids") or []),
            amount=amount,
            app_fee=app_fee,
            fee_waived=bool(fields.get("fee_waived") or False),
            created_at=now,
            updated_at=now,
        )
        with self._path.open("a") as f:
            f.write(json.dumps(item.to_dict(), separators=(",", ":")) + "\n")
        return item

    def update(self, app_id: str, **fields) -> Application:
        items = self._read_all()
        for it in items:
            if it.id == app_id:
                if fields.get("name") is not None:
                    it.name = self._validate_name(fields["name"])
                if fields.get("org") is not None:
                    it.org = fields["org"]
                if fields.get("type") is not None:
                    it.type = self._validate_type(fields["type"])
                if fields.get("status") is not None:
                    it.status = self._validate_status(fields["status"])
                if fields.get("decision_result") is not None:
                    it.decision_result = self._validate_decision_result(fields["decision_result"])
                if "deadline" in fields and fields["deadline"] is not None:
                    it.deadline = fields["deadline"]
                if fields.get("url") is not None:
                    it.url = fields["url"]
                if fields.get("notes") is not None:
                    it.notes = fields["notes"]
                if fields.get("requirements") is not None:
                    it.requirements = [self._normalize_requirement(r) for r in fields["requirements"]]
                if fields.get("document_ids") is not None:
                    it.document_ids = list(fields["document_ids"])
                if fields.get("amount") is not None:
                    it.amount = self._validate_amount(fields["amount"], "amount")
                if fields.get("app_fee") is not None:
                    it.app_fee = self._validate_amount(fields["app_fee"], "app_fee")
                if fields.get("fee_waived") is not None:
                    it.fee_waived = bool(fields["fee_waived"])
                if fields.get("archived") is not None:
                    it.archived = bool(fields["archived"])
                it.updated_at = self._now_iso()
                self._write_all(items)
                return it
        raise KeyError(app_id)

    def delete(self, app_id: str) -> None:
        items = self._read_all()
        new_items = [i for i in items if i.id != app_id]
        if len(new_items) == len(items):
            raise KeyError(app_id)
        self._write_all(new_items)

    # === requirements ===

    def add_requirement(self, app_id: str, label: str) -> Application:
        items = self._read_all()
        for it in items:
            if it.id == app_id:
                label = (label or "").strip()
                if not label:
                    raise ValueError("label is required and cannot be empty")
                it.requirements.append({"id": self._new_id(), "label": label, "done": False})
                it.updated_at = self._now_iso()
                self._write_all(items)
                return it
        raise KeyError(app_id)

    def update_requirement(self, app_id: str, req_id: str, **fields) -> Application:
        items = self._read_all()
        for it in items:
            if it.id == app_id:
                for r in it.requirements:
                    if r["id"] == req_id:
                        if fields.get("label") is not None:
                            r["label"] = str(fields["label"]).strip()
                        if fields.get("done") is not None:
                            r["done"] = bool(fields["done"])
                        it.updated_at = self._now_iso()
                        self._write_all(items)
                        return it
                raise KeyError(req_id)
        raise KeyError(app_id)

    def delete_requirement(self, app_id: str, req_id: str) -> Application:
        items = self._read_all()
        for it in items:
            if it.id == app_id:
                new_reqs = [r for r in it.requirements if r["id"] != req_id]
                if len(new_reqs) == len(it.requirements):
                    raise KeyError(req_id)
                it.requirements = new_reqs
                it.updated_at = self._now_iso()
                self._write_all(items)
                return it
        raise KeyError(app_id)

    # === aggregates ===

    def upcoming_deadlines(self, days: int = 30) -> list[Application]:
        """Applications with deadline set, not past, status != decision.

        Sorted ascending by deadline, capped to the next `days`.
        """
        items = self._read_all()
        today = date.today()
        horizon = today + timedelta(days=days)
        out = []
        for i in items:
            if not i.deadline:
                continue
            if i.status == "decision" or i.archived:
                continue
            try:
                d = date.fromisoformat(i.deadline)
            except ValueError:
                continue
            if d < today or d > horizon:
                continue
            out.append(i)
        out.sort(key=lambda i: i.deadline)
        return out

    def costs(self) -> dict:
        """Money aggregate: fees owed/waived, scholarship awards, by-type totals.

        Nulls (amount/app_fee unset) count as 0.
        """
        items = self._read_all()
        fees_due = 0.0
        fees_waived = 0.0
        potential_awards = 0.0
        won_awards = 0.0
        by_type: dict[str, dict] = {}

        for i in items:
            fee = i.app_fee or 0.0
            amount = i.amount or 0.0

            if i.fee_waived:
                fees_waived += fee
            elif i.status != "decision":
                fees_due += fee

            if i.type == "scholarship" and i.status != "decision":
                potential_awards += amount

            if i.decision_result == "accepted":
                won_awards += amount

            bucket = by_type.setdefault(i.type or "", {"count": 0, "amount": 0.0})
            bucket["count"] += 1
            bucket["amount"] += amount

        return {
            "fees_due": fees_due,
            "fees_waived": fees_waived,
            "potential_awards": potential_awards,
            "won_awards": won_awards,
            "by_type": by_type,
        }
