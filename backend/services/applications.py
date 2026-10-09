"""Applications service — the flagship Applications Pipeline module.

Tracks university / scholarship / exchange applications as a local
JSONL ledger: one line per application, requirements checklist nested
inline. Mirrors backend/services/inbox.py: JSONL storage, atomic
rewrite on update, uuid4 hex ids, ISO date/datetime strings.
"""
from __future__ import annotations

import csv
import io
import json
import math
import os
import re
import tempfile
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional


TYPES = ("undergrad", "grad", "scholarship", "exchange")
STATUSES = ("researching", "preparing", "submitted", "secondaries", "interview", "decision")
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
    # Additive scholarship fields (no CURRENT_FORMAT bump: old records just default).
    renewable: bool = False
    awarded_amount: Optional[float] = None  # what was actually won
    eligibility: str = ""
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
        # Sync handlers run in a threadpool: serialize every read-modify-write.
        self._lock = threading.RLock()

    # === internal I/O ===

    def _read_all(self) -> list[Application]:
        return self._read_lines()[0]

    def _read_lines(self) -> tuple[list[Application], list[str]]:
        """Parsed items plus the raw text of every unparseable line (kept on rewrite)."""
        if not self._path.exists():
            return [], []
        items: list[Application] = []
        bad: list[str] = []
        with self._path.open() as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                    items.append(Application.from_dict(d))
                except (json.JSONDecodeError, TypeError) as e:
                    print(f"[applications] malformed line preserved: {e!r}")
                    bad.append(line)
        return items, bad

    def _write_all(self, items: list[Application]) -> None:
        """Atomic rewrite via a unique tmp file. Unparseable lines are carried over
        verbatim so a rewrite never destroys data the app could not read."""
        with self._lock:
            _, bad = self._read_lines()
            fd, tmp_name = tempfile.mkstemp(
                dir=str(self.data_dir), prefix="items.", suffix=".jsonl.tmp"
            )
            try:
                with os.fdopen(fd, "w") as f:
                    for it in items:
                        f.write(json.dumps(it.to_dict(), separators=(",", ":")) + "\n")
                    for line in bad:
                        f.write(line + "\n")
                os.replace(tmp_name, self._path)
            except BaseException:
                try:
                    os.unlink(tmp_name)
                except OSError:
                    pass
                raise

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
        if not math.isfinite(amount):
            raise ValueError(f"{field_name} must be a finite number")
        if amount < 0:
            raise ValueError(f"{field_name} must be >= 0")
        return amount

    def _validate_deadline(self, value) -> Optional[str]:
        """YYYY-MM-DD or empty/None (cleared)."""
        if value is None:
            return None
        v = str(value).strip()
        if not v:
            return None
        try:
            return date.fromisoformat(v).isoformat()
        except ValueError:
            raise ValueError("deadline must be a date in YYYY-MM-DD format")

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
        deadline = self._validate_deadline(fields.get("deadline"))
        now = self._now_iso()
        item = Application(
            id=self._new_id(),
            name=name,
            org=fields.get("org") or "",
            type=type_,
            status=status,
            decision_result=decision_result,
            deadline=deadline,
            url=fields.get("url") or "",
            notes=fields.get("notes") or "",
            requirements=requirements,
            document_ids=list(fields.get("document_ids") or []),
            amount=amount,
            app_fee=app_fee,
            fee_waived=bool(fields.get("fee_waived") or False),
            renewable=bool(fields.get("renewable") or False),
            awarded_amount=self._validate_amount(fields.get("awarded_amount"), "awarded_amount"),
            eligibility=fields.get("eligibility") or "",
            created_at=now,
            updated_at=now,
        )
        line = json.dumps(item.to_dict(), separators=(",", ":")) + "\n"
        with self._lock:
            prefix = ""
            if self._path.exists() and self._path.stat().st_size > 0:
                with self._path.open("rb") as rf:
                    rf.seek(-1, os.SEEK_END)
                    if rf.read(1) != b"\n":
                        prefix = "\n"  # last line was cut off; don't glue onto it
            with self._path.open("a") as f:
                f.write(prefix + line)
        return item

    def update(self, app_id: str, **fields) -> Application:
        with self._lock:
            return self._update_locked(app_id, **fields)

    def _update_locked(self, app_id: str, **fields) -> Application:
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
                if "deadline" in fields:
                    it.deadline = self._validate_deadline(fields["deadline"])
                if fields.get("url") is not None:
                    it.url = fields["url"]
                if fields.get("notes") is not None:
                    it.notes = fields["notes"]
                if fields.get("requirements") is not None:
                    it.requirements = [self._normalize_requirement(r) for r in fields["requirements"]]
                if fields.get("document_ids") is not None:
                    it.document_ids = list(fields["document_ids"])
                if "amount" in fields:
                    it.amount = self._validate_amount(fields["amount"], "amount")
                if "app_fee" in fields:
                    it.app_fee = self._validate_amount(fields["app_fee"], "app_fee")
                if fields.get("fee_waived") is not None:
                    it.fee_waived = bool(fields["fee_waived"])
                if fields.get("archived") is not None:
                    it.archived = bool(fields["archived"])
                if fields.get("renewable") is not None:
                    it.renewable = bool(fields["renewable"])
                if "awarded_amount" in fields:
                    it.awarded_amount = self._validate_amount(fields["awarded_amount"], "awarded_amount")
                if fields.get("eligibility") is not None:
                    it.eligibility = str(fields["eligibility"])
                it.updated_at = self._now_iso()
                self._write_all(items)
                return it
        raise KeyError(app_id)

    def delete(self, app_id: str) -> None:
        with self._lock:
            items = self._read_all()
            new_items = [i for i in items if i.id != app_id]
            if len(new_items) == len(items):
                raise KeyError(app_id)
            self._write_all(new_items)

    # === requirements ===

    def add_requirement(self, app_id: str, label: str) -> Application:
        with self._lock:
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
        with self._lock:
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
        with self._lock:
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
            elif i.status != "decision" and not i.archived:
                fees_due += fee

            if i.type == "scholarship" and i.status != "decision" and not i.archived:
                potential_awards += amount

            if i.decision_result == "accepted" and i.status == "decision" and not i.archived:
                if i.awarded_amount is not None:
                    won_awards += i.awarded_amount
                elif i.type == "scholarship":
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

    # === scholarships ===

    def scholarship_summary(self, doc_titles: Optional[dict] = None) -> dict:
        """Scholarship tracker rollup. `doc_titles` maps document_id -> title
        (best-effort; None skips the essay-reuse section's titles)."""
        items = [i for i in self._read_all() if i.type == "scholarship"]
        count_by_status: dict[str, int] = {}
        for i in items:
            count_by_status[i.status] = count_by_status.get(i.status, 0) + 1
        live = [i for i in items if not i.archived]
        potential_total = sum(i.amount or 0.0 for i in live if i.status != "decision")
        won = [i for i in items if i.awarded_amount]
        won_total = sum(i.awarded_amount or 0.0 for i in won)
        pending_count = sum(1 for i in live if i.status != "decision")
        today = date.today()
        upcoming = []
        for i in live:
            if not i.deadline or i.status == "decision":
                continue
            try:
                d = date.fromisoformat(i.deadline)
            except ValueError:
                continue
            if d >= today:
                upcoming.append((d, i))
        upcoming.sort(key=lambda t: t[0])
        next_deadlines = [
            {"id": i.id, "name": i.name, "deadline": i.deadline, "amount": i.amount}
            for _, i in upcoming[:5]
        ]
        # doc_titles values: a title str, or (title, linked_application_ids).
        titles: dict[str, str] = {}
        links: dict[str, list] = {}
        for doc_id, v in (doc_titles or {}).items():
            if isinstance(v, (tuple, list)):
                titles[doc_id] = v[0] if v else ""
                links[doc_id] = list(v[1]) if len(v) > 1 and v[1] else []
            else:
                titles[doc_id] = v or ""
        by_doc: dict[str, list] = {}
        live_by_id = {i.id: i for i in live}
        for i in live:
            for doc_id in dict.fromkeys(i.document_ids):
                by_doc.setdefault(doc_id, []).append({"id": i.id, "name": i.name})
        for doc_id, app_ids in links.items():
            seen = {u["id"] for u in by_doc.get(doc_id, [])}
            for aid in dict.fromkeys(app_ids):
                a = live_by_id.get(aid)
                if a and aid not in seen:
                    by_doc.setdefault(doc_id, []).append({"id": a.id, "name": a.name})
        essays = [
            {"document_id": doc_id, "title": titles.get(doc_id, ""), "used_by": used}
            for doc_id, used in by_doc.items()
            if used
        ]
        essays.sort(key=lambda e: (-len(e["used_by"]), e["document_id"]))
        return {
            "count_by_status": count_by_status,
            "potential_total": potential_total,
            "won_total": won_total,
            "won_count": len(won),
            "pending_count": pending_count,
            "next_deadlines": next_deadlines,
            "essays": essays,
        }

    def import_scholarships_csv(self, text: str, dry_run: bool = False) -> dict:
        """Import scholarships from CSV text. Bad rows are reported, never fatal."""
        text = (text or "").lstrip("\ufeff")
        rows = list(csv.reader(io.StringIO(text)))
        rows = [r for r in rows if any(c.strip() for c in r)]
        result: dict = {"created": 0, "skipped_duplicates": 0, "errors": [], "rows": [], "warnings": []}
        if not rows:
            result["errors"].append({"row": 0, "message": "empty CSV"})
            return result
        cols: dict[str, int] = {}
        ignored: list[str] = []
        for idx, h in enumerate(rows[0]):
            canon = _csv_canon(h)
            if canon and canon not in cols:
                cols[canon] = idx
            elif not canon and h.strip():
                ignored.append(h.strip())
        if "name" not in cols:
            result["errors"].append({"row": 1, "message": "no name/title/scholarship column in header"})
            return result

        if ignored:
            result["warnings"].append(
                {"message": "Ignored unrecognized columns: " + ", ".join(ignored)}
            )
        existing = {
            _dedupe_key(i.name, i.org, i.deadline) for i in self._read_all() if i.type == "scholarship"
        }
        seen = set(existing)
        header_len = len(rows[0])
        for n, r in enumerate(rows[1:], start=2):
            if len(r) > header_len and any(c.strip() for c in r[header_len:]):
                result["errors"].append({
                    "row": n,
                    "message": f"Row {n} has {len(r)} fields but the header has {header_len}; quote values that contain commas",
                })
                continue

            def cell(k: str) -> str:
                j = cols.get(k)
                return r[j].strip() if j is not None and j < len(r) else ""

            name = cell("name")
            if not name:
                result["errors"].append({"row": n, "message": "missing name"})
                continue
            deadline = None
            if cell("deadline"):
                deadline = parse_flexible_date(cell("deadline"))
                if deadline is None:
                    result["errors"].append({"row": n, "message": f"unparseable deadline {cell('deadline')!r}"})
                    continue
            amount = None
            if cell("amount"):
                try:
                    amount = float(re.sub(r"[$,\s]", "", cell("amount")))
                    if amount < 0 or not math.isfinite(amount):
                        raise ValueError
                except ValueError:
                    result["errors"].append({"row": n, "message": f"invalid amount {cell('amount')!r}"})
                    continue
            org = cell("org")
            key = _dedupe_key(name, org, deadline)
            if key in seen:
                result["skipped_duplicates"] += 1
                continue
            seen.add(key)
            parsed = {
                "name": name, "org": org, "type": "scholarship", "amount": amount,
                "deadline": deadline, "url": cell("url"), "notes": cell("notes"),
                "eligibility": cell("eligibility"),
                "renewable": cell("renewable").lower() in ("y", "yes", "true", "1", "x"),
            }
            result["rows"].append({"row": n, **parsed})
            if not dry_run:
                self.add(**parsed)
                result["created"] += 1
        if dry_run:
            result["created"] = 0
        else:
            result.pop("rows")
        return result


_CSV_ALIASES = {
    "name": "name", "title": "name", "scholarship": "name", "scholarshipname": "name",
    "organization": "org", "org": "org", "provider": "org", "sponsor": "org",
    "amount": "amount", "award": "amount", "awardamount": "amount",
    "deadline": "deadline", "duedate": "deadline", "due": "deadline",
    "url": "url", "link": "url", "website": "url",
    "notes": "notes", "note": "notes",
    "eligibility": "eligibility", "renewable": "renewable",
}


def _csv_canon(header: str) -> Optional[str]:
    """Map a header to a canonical column: exact alias first, then keyword match."""
    key = re.sub(r"[^a-z]", "", header.lower())
    if not key:
        return None
    if key in _CSV_ALIASES:
        return _CSV_ALIASES[key]
    if key in ("awardname", "programname"):
        return "name"
    if "deadline" in key or key.startswith("due") or key.endswith("duedate"):
        return "deadline"
    if "amount" in key or key.startswith("award") or "value" in key:
        return "amount"
    if "provider" in key or "sponsor" in key or "organi" in key:
        return "org"
    if "eligib" in key:
        return "eligibility"
    if "scholarship" in key or key in ("programname", "awardname"):
        return "name"
    if "url" in key or "link" in key or "website" in key:
        return "url"
    return None


def _dedupe_key(name: str, org: str, deadline: Optional[str]) -> tuple:
    return ((name or "").strip().lower(), (org or "").strip().lower(), deadline or "")


def parse_flexible_date(s: str) -> Optional[str]:
    """ISO, M/D/YYYY, or 'Month D, YYYY' -> ISO date string; None if unparseable."""
    s = (s or "").strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%B %d, %Y", "%b %d, %Y", "%B %d %Y", "%b %d %Y"):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    return None
