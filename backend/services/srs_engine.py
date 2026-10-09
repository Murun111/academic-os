"""SuperMemo-2 (SM-2) Spaced Repetition Engine for Academic OS.

Implements the classic SuperMemo-2 algorithm for optimal memory retention,
calculating next review intervals, repetition counts, and ease factors.
"""
from __future__ import annotations

from datetime import datetime, time, timezone, timedelta
from typing import TypedDict, Literal

Rating = Literal["again", "hard", "good", "easy"]

RATING_MAP: dict[Rating, int] = {
    "again": 1,
    "hard": 2,
    "good": 3,
    "easy": 4,
}

DEFAULT_EASE_FACTOR = 2.5
MIN_EASE_FACTOR = 1.3


class SrsState(TypedDict):
    ease_factor: float
    repetition: int
    interval_days: int
    next_review: str  # ISO 8601 string
    last_reviewed: str  # ISO 8601 string
    lapses: int


def initial_srs_state() -> SrsState:
    now_iso = datetime.now(timezone.utc).isoformat()
    return {
        "ease_factor": DEFAULT_EASE_FACTOR,
        "repetition": 0,
        "interval_days": 0,
        "next_review": now_iso,
        "last_reviewed": "",
        "lapses": 0,
    }


def _start_of_local_day(now: datetime, days: int) -> datetime:
    """Local midnight `days` days after `now`, as UTC.

    Snapping to the day boundary (instead of now + N*24h) keeps a daily habit
    stable: a card reviewed at 20:30 is due all of the target day, not from 20:30.
    """
    local = now.astimezone()
    target = local.date() + timedelta(days=days)
    return datetime.combine(target, time.min).astimezone().astimezone(timezone.utc)


def calculate_next_review(
    rating: Rating | int,
    current_ease: float = DEFAULT_EASE_FACTOR,
    repetition: int = 0,
    interval_days: int = 0,
    lapses: int = 0,
    now: datetime | None = None,
) -> SrsState:
    """Calculate the next SM-2 interval and ease factor given a review rating."""
    if now is None:
        now = datetime.now(timezone.utc)

    now_iso = now.isoformat()

    if isinstance(rating, str):
        q = RATING_MAP.get(rating, 3)
    else:
        q = max(1, min(4, rating))

    # Convert 1-4 scale to SuperMemo 0-5 scale equivalent for EF adjustment
    # 1 -> 1, 2 -> 2, 3 -> 4, 4 -> 5
    sm_q = 1 if q == 1 else (2 if q == 2 else (4 if q == 3 else 5))

    # Calculate new ease factor
    new_ef = current_ease + (0.1 - (5 - sm_q) * (0.08 + (5 - sm_q) * 0.02))
    new_ef = max(MIN_EASE_FACTOR, round(new_ef, 3))

    new_lapses = lapses

    if q < 3:
        # Failed or Hard struggle
        if q == 1:
            new_repetition = 0
            new_interval = 1
            new_lapses += 1
        else:  # Hard (q == 2)
            new_repetition = max(1, repetition)
            base = max(1, interval_days)
            new_interval = max(base + 1, int(round(base * 1.2)))
    else:
        # Success (Good or Easy)
        if repetition == 0:
            new_interval = 1
            new_repetition = 1
        elif repetition == 1:
            new_interval = 6
            new_repetition = 2
        else:
            base_interval = max(1, interval_days)
            new_interval = max(1, int(round(base_interval * new_ef)))
            if q == 4:  # Easy bonus
                new_interval = int(round(new_interval * 1.3))
            new_repetition = repetition + 1

    next_date = _start_of_local_day(now, new_interval)

    return {
        "ease_factor": new_ef,
        "repetition": new_repetition,
        "interval_days": new_interval,
        "next_review": next_date.isoformat(),
        "last_reviewed": now_iso,
        "lapses": new_lapses,
    }
