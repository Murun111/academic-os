"""Syllabus extraction for Academic OS.

Turns raw syllabus text into structured assessment items using the shared
learning_ai LLM plumbing. The model only copies what the syllabus states;
everything it returns is verified against the source text afterwards.
"""
from __future__ import annotations

import calendar
import difflib
import re
from datetime import date, timedelta
from typing import Any, Optional

from backend.llm_hub import ChatMessage
from backend.services import learning_ai
from backend.services.learning_ai import (  # noqa: F401  (re-exported for routers)
    LearningAIBadOutput,
    LearningAIUnavailable,
    _ai_structured,
)

CHUNK_SIZE = 6000
CHUNK_OVERLAP = 400
KINDS = ("assignment", "exam", "quiz", "project", "reading", "other")
FUZZY_THRESHOLD = 0.85

_MONTHS = {m.lower(): i for i, m in enumerate(calendar.month_name) if m}
_MONTHS.update({m.lower(): i for i, m in enumerate(calendar.month_abbr) if m})
_MONTHS["sept"] = 9
_DAYS = {d.lower(): i for i, d in enumerate(calendar.day_name)}
_DAYS.update({d.lower(): i for i, d in enumerate(calendar.day_abbr)})
_DAYS.update({"tues": 1, "thur": 3, "thurs": 3})


def chunk_text(text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """Split text into ~size char chunks with overlap, preferring newline breaks."""
    text = text.strip()
    if len(text) <= size:
        return [text] if text else []
    chunks, start = [], 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            nl = text.rfind("\n", start + size // 2, end)
            if nl != -1:
                end = nl
        chunks.append(text[start:end])
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return chunks


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w%$.]+", " ", s.lower())).strip()


def _parse_iso(s: str) -> Optional[date]:
    m = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})(?:[T ].*)?", s.strip())
    if not m:
        return None
    try:
        return date(int(m[1]), int(m[2]), int(m[3]))
    except ValueError:
        return None


def _to_date(s: Any, term_start: Optional[date], year: Optional[int]) -> Optional[date]:
    """Resolve a date string to a date, or None if it cannot be resolved safely."""
    if not isinstance(s, str) or not s.strip():
        return None
    s = s.strip()
    iso = _parse_iso(s)
    if iso:
        return iso
    low = s.lower().replace(",", " ")

    # Explicit month/day beats a "week N" label. Lookahead lets matches overlap so a
    # leading non-month word ("Week 3 (Sept 14)", "Session 4, Oct 20") is skipped.
    mon = day = yr = None
    for m in re.finditer(r"(?=\b([a-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?(?:\s+(\d{4}))?\b)", low):
        if m[1] in _MONTHS:
            mon, day, yr = _MONTHS[m[1]], int(m[2]), m[3]
            break
    if not mon:
        for m in re.finditer(r"(?=\b(\d{1,2})(?:st|nd|rd|th)?\s+([a-z]{3,9})\.?(?:\s+(\d{4}))?\b)", low):
            if m[2] in _MONTHS:
                mon, day, yr = _MONTHS[m[2]], int(m[1]), m[3]
                break
    if mon:
        y = int(yr) if yr else year
        return _safe_date(y, mon, day)

    # numeric "M/D[/YY[YY]]", possibly with a weekday prefix ("Tue 9/15")
    m = re.search(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b", low)
    if m:
        y = int(m[3]) if m[3] else year
        if y is not None and y < 100:
            y += 2000
        return _safe_date(y, int(m[1]), int(m[2]))

    return _week_date(low, term_start)


def _week_date(low: str, term_start: Optional[date]) -> Optional[date]:
    """Relative: "Friday of week 3" / "week 3 friday" / "week 3" (needs term_start)."""
    wk = re.search(r"\bweek\s*(\d{1,2})\b", low)
    if wk and term_start:
        wd = next((_DAYS[w] for w in re.findall(r"[a-z]+", low) if w in _DAYS), None)
        monday = term_start - timedelta(days=term_start.weekday())
        base = monday + timedelta(weeks=int(wk[1]) - 1)
        return base + timedelta(days=wd if wd is not None else term_start.weekday())
    return None


def _has_explicit_date(low: str) -> bool:
    low = low.replace(",", " ")
    if re.search(r"\b\d{1,2}/\d{1,2}\b", low) or _parse_iso(low.strip()):
        return True
    for m in re.finditer(r"(?=\b([a-z]{3,9})\.?\s+\d{1,2}\b)", low):
        if m[1] in _MONTHS:
            return True
    for m in re.finditer(r"(?=\b\d{1,2}(?:st|nd|rd|th)?\s+([a-z]{3,9})\b)", low):
        if m[1] in _MONTHS:
            return True
    return False


def _infer_year(text: str) -> Optional[int]:
    """Year from the syllabus text: "Fall 2026" style first, else the most common 20xx."""
    m = re.search(r"\b(?:fall|spring|summer|winter|autumn)\s+(?:term\s+|semester\s+)?(20\d\d)\b", text, re.I)
    if m:
        return int(m[1])
    years = re.findall(r"\b(20\d\d)\b", text)
    if years:
        return int(max(set(years), key=lambda y: (years.count(y), y)))
    return None


def _academic_year(today: Optional[date] = None) -> int:
    return (today or date.today()).year


def _safe_date(y: Optional[int], mon: int, day: int) -> Optional[date]:
    if y is None:
        return None
    try:
        return date(y, mon, day)
    except ValueError:
        return None


def _num(v: Any) -> Optional[float]:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        m = re.search(r"-?\d+(?:\.\d+)?", v)
        return float(m[0]) if m else None
    return None


def _source_in_text(src: str, text_norm: str, windows: list[str]) -> bool:
    n = _norm(src)
    if not n:
        return False
    if n in text_norm:
        return True
    return any(difflib.SequenceMatcher(None, n, w).ratio() >= FUZZY_THRESHOLD for w in windows)


def _windows(text: str) -> list[str]:
    lines = [_norm(l) for l in text.splitlines() if l.strip()]
    lines = [l for l in lines if l]
    return lines + [f"{a} {b}" for a, b in zip(lines, lines[1:])]


def _build_prompt(chunk: str, term_start: Optional[str], term_year: Optional[int]) -> str:
    ctx = ""
    if term_start or term_year:
        ctx = f"Term context (for your reference only, do not use it to invent dates): start={term_start or 'unknown'}, year={term_year or 'unknown'}.\n"
    return f"""You extract graded work from a course syllabus.
Copy ONLY what the syllabus text states. Never invent dates, weights or points. If a due date is not stated, use null. If a weight or points value is not stated, use null.
For "due", copy the date exactly as written (for example "Sept 14", "10/3", "Friday of week 3", "2026-09-14").
{ctx}
Return ONLY a valid JSON object with these keys:
- "course_name": course title if stated, else null
- "items": array of objects with:
  - "title": name of the assignment, exam, quiz, project or reading (string)
  - "kind": one of "assignment", "exam", "quiz", "project", "reading", "other"
  - "due": date as written, or null
  - "weight": percent of the final grade as a number, or null
  - "points": point value as a number, or null
  - "source_line": the exact snippet of syllabus text this item came from (string)
- "grading": array of {{"category": string, "weight": number in percent}} from the grading breakdown, if present

Syllabus text:
\"\"\"
{chunk}
\"\"\"
"""


def _parse_chunk(parsed: Any) -> Optional[dict[str, Any]]:
    if isinstance(parsed, list):
        parsed = {"items": parsed}
    if not isinstance(parsed, dict):
        return None
    items = parsed.get("items")
    if items is None:
        items = []
    if not isinstance(items, list):
        return None
    grading = parsed.get("grading")
    return {
        "course_name": parsed.get("course_name"),
        "items": [i for i in items if isinstance(i, dict)],
        "grading": [g for g in grading if isinstance(g, dict)] if isinstance(grading, list) else [],
    }


async def extract_syllabus(
    text: str,
    term_start: Optional[str] = None,
    term_year: Optional[int] = None,
) -> dict[str, Any]:
    ts = _parse_iso(term_start) if term_start else None
    year = term_year or (ts.year if ts else None)
    warnings: list[str] = []
    if year is None:
        year = _infer_year(text or "")
        if year is None:
            year = _academic_year()
            warnings.append(f"No term year was given or found, so dates without a year were read as {year}. Check them.")
    if term_start and not ts:
        warnings.append("term_start is not a valid ISO date and was ignored.")

    # Look up learning_ai._hub_chat at call time so tests can monkeypatch it.
    chunks = chunk_text(text or "")
    if not chunks:
        raise LearningAIBadOutput("The syllabus text is empty.")

    raw_items: list[dict[str, Any]] = []
    raw_grading: list[dict[str, Any]] = []
    course_name: Optional[str] = None
    for ch in chunks:
        prompt = _build_prompt(ch, term_start if ts else None, year)
        res = await _ai_structured(prompt, _parse_chunk, "syllabus data")
        if not course_name and isinstance(res["course_name"], str) and res["course_name"].strip():
            course_name = res["course_name"].strip()
        raw_items += res["items"]
        raw_grading += res["grading"]

    text_norm = _norm(text)
    windows = _windows(text)

    items: dict[tuple[str, Optional[str], str], dict[str, Any]] = {}
    dropped = bad_dates = 0
    for it in raw_items:
        title = it.get("title")
        title = title.strip() if isinstance(title, str) else ""
        src = it.get("source_line")
        src = src.strip() if isinstance(src, str) else ""
        if not title:
            continue
        if not src or not _source_in_text(src, text_norm, windows):
            dropped += 1
            continue
        kind = it.get("kind")
        kind = kind.strip().lower() if isinstance(kind, str) else "other"
        if kind not in KINDS:
            kind = "other"
        due_raw = it.get("due")
        due = _to_date(due_raw, ts, year)
        # The model's weekday arithmetic is unreliable: when the source line is a
        # "Friday of Week N" reference with no explicit date, compute it in code.
        if ts and not _has_explicit_date(src):
            wdate = _week_date(src.lower(), ts)
            if wdate:
                due = wdate
        if due_raw not in (None, "") and due is None:
            bad_dates += 1
        rec = {
            "title": title, "kind": kind,
            "due": due.isoformat() if due else None,
            "weight": _num(it.get("weight")), "points": _num(it.get("points")),
            "source_line": src,
        }
        key = (_norm(title), rec["due"], "" if rec["due"] else _norm(src))
        if key in items:
            prev = items[key]
            for f in ("weight", "points"):
                if prev[f] is None:
                    prev[f] = rec[f]
            if prev["kind"] == "other":
                prev["kind"] = rec["kind"]
        else:
            items[key] = rec

    grading: dict[str, dict[str, Any]] = {}
    for g in raw_grading:
        cat = g.get("category")
        w = _num(g.get("weight"))
        if isinstance(cat, str) and cat.strip() and w is not None:
            grading.setdefault(_norm(cat), {"category": cat.strip(), "weight": w})

    if dropped:
        warnings.append(
            f"Dropped {dropped} item(s) whose source text could not be found in the syllabus.")
    if bad_dates:
        warnings.append(
            f"{bad_dates} date(s) could not be resolved and were left empty"
            + ("" if ts else " (dates like \"Week 3\" need a term start date)") + ".")

    return {
        "course_name": course_name,
        "items": list(items.values()),
        "grading": list(grading.values()),
        "warnings": warnings,
    }
