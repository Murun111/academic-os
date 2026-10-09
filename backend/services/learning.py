"""Core Learning Service for Academic OS.

Manages Flashcards & SRS decks, Quizzes, Concept Mastery Matrix, Study Guides,
and Deep Work sessions with local JSON/JSONL persistence.
"""
from __future__ import annotations

import functools
import json
import os
import tempfile
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from backend.services.srs_engine import (
    Rating,
    calculate_next_review,
    initial_srs_state,
)


class LearningServiceError(Exception):
    pass


class LearningValidationError(LearningServiceError):
    """Bad input (blank title, empty card side); routers map this to 422, not 404."""


# Sync routes run in the threadpool and every mutation is read-all/modify/write-all,
# so all public service methods serialise on one re-entrant lock.
_LOCK = threading.RLock()


def _locked(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        with _LOCK:
            return fn(*args, **kwargs)
    return wrapper


class LearningService:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.decks_file = self.data_dir / "decks.jsonl"
        self.quizzes_file = self.data_dir / "quizzes.jsonl"
        self.mastery_file = self.data_dir / "mastery.json"
        self.guides_file = self.data_dir / "guides.jsonl"
        self.focus_file = self.data_dir / "focus.jsonl"

    # ── Helpers ────────────────────────────────────────────────────────
    def _read_jsonl(self, path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        items = []
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        items.append(json.loads(line))
                    except Exception:
                        continue
        return items

    def _write_jsonl(self, path: Path, items: list[dict[str, Any]]) -> None:
        fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=path.stem + ".", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                for item in items:
                    f.write(json.dumps(item, ensure_ascii=False) + "\n")
            os.replace(tmp_name, path)
        except BaseException:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise

    def _read_json(self, path: Path, default: Any) -> Any:
        if not path.exists():
            return default
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return default

    def _write_json(self, path: Path, data: Any) -> None:
        fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=path.stem + ".", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            os.replace(tmp_name, path)
        except BaseException:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise

    # ── Flashcards & Decks ─────────────────────────────────────────────
    @_locked
    def list_decks(self, course_id: Optional[str] = None) -> list[dict[str, Any]]:
        decks = self._read_jsonl(self.decks_file)
        now_iso = datetime.now(timezone.utc).isoformat()
        res = []
        for d in decks:
            if course_id and d.get("course_id") != course_id:
                continue
            cards = d.get("cards", [])
            due_count = sum(1 for c in cards if not c.get("srs", {}).get("next_review") or c.get("srs", {}).get("next_review") <= now_iso)
            total_count = len(cards)
            res.append({
                **d,
                "total_cards": total_count,
                "due_cards": due_count,
            })
        return res

    @_locked
    def get_deck(self, deck_id: str) -> dict[str, Any]:
        decks = self._read_jsonl(self.decks_file)
        for d in decks:
            if d.get("id") == deck_id:
                now_iso = datetime.now(timezone.utc).isoformat()
                cards = d.get("cards", [])
                due_count = sum(1 for c in cards if not c.get("srs", {}).get("next_review") or c.get("srs", {}).get("next_review") <= now_iso)
                return {
                    **d,
                    "total_cards": len(cards),
                    "due_cards": due_count,
                }
        raise LearningServiceError(f"Deck not found: {deck_id}")

    @_locked
    def create_deck(
        self,
        title: str,
        description: str = "",
        course_id: Optional[str] = None,
        course_name: Optional[str] = None,
        tags: Optional[list[str]] = None,
        cards: Optional[list[dict[str, Any]]] = None,
    ) -> dict[str, Any]:
        if not (title or "").strip():
            raise LearningValidationError("Deck title is required")
        decks = self._read_jsonl(self.decks_file)
        deck_id = f"deck_{uuid.uuid4().hex[:8]}"
        now_iso = datetime.now(timezone.utc).isoformat()

        formatted_cards = []
        if cards:
            for c in cards:
                card_id = c.get("id") or f"card_{uuid.uuid4().hex}"
                srs = c.get("srs") or initial_srs_state()
                formatted_cards.append({
                    "id": card_id,
                    "front": c.get("front", ""),
                    "back": c.get("back", ""),
                    "hint": c.get("hint", ""),
                    "explanation": c.get("explanation", ""),
                    "tags": c.get("tags", []),
                    "srs": srs,
                    "created_at": now_iso,
                })

        new_deck = {
            "id": deck_id,
            "title": title.strip(),
            "description": description.strip(),
            "course_id": course_id,
            "course_name": course_name,
            "tags": tags or [],
            "cards": formatted_cards,
            "created_at": now_iso,
            "updated_at": now_iso,
        }
        decks.insert(0, new_deck)
        self._write_jsonl(self.decks_file, decks)
        return {
            **new_deck,
            "total_cards": len(formatted_cards),
            "due_cards": len(formatted_cards),
        }

    @_locked
    def update_deck(self, deck_id: str, **fields: Any) -> dict[str, Any]:
        decks = self._read_jsonl(self.decks_file)
        found = None
        for i, d in enumerate(decks):
            if d.get("id") == deck_id:
                for k, v in fields.items():
                    if k == "title":
                        if v is None:
                            continue
                        v = v.strip()
                        if not v:
                            raise LearningValidationError("Deck title is required")
                    elif v is None and k in ("description", "tags"):
                        continue
                    # course_id / course_name may be cleared with an explicit null
                    d[k] = v
                d["updated_at"] = datetime.now(timezone.utc).isoformat()
                decks[i] = d
                found = d
                break
        if not found:
            raise LearningServiceError(f"Deck not found: {deck_id}")
        self._write_jsonl(self.decks_file, decks)
        return found

    @_locked
    def delete_deck(self, deck_id: str) -> None:
        decks = self._read_jsonl(self.decks_file)
        new_decks = [d for d in decks if d.get("id") != deck_id]
        if len(new_decks) == len(decks):
            raise LearningServiceError(f"Deck not found: {deck_id}")
        self._write_jsonl(self.decks_file, new_decks)

    @_locked
    def add_card(self, deck_id: str, front: str, back: str, hint: str = "", explanation: str = "", tags: Optional[list[str]] = None) -> dict[str, Any]:
        if not front.strip() or not back.strip():
            raise LearningValidationError("A card needs both a front and a back")
        decks = self._read_jsonl(self.decks_file)
        found = None
        for d in decks:
            if d.get("id") == deck_id:
                now_iso = datetime.now(timezone.utc).isoformat()
                card_id = f"card_{uuid.uuid4().hex}"
                card = {
                    "id": card_id,
                    "front": front.strip(),
                    "back": back.strip(),
                    "hint": hint.strip(),
                    "explanation": explanation.strip(),
                    "tags": tags or [],
                    "srs": initial_srs_state(),
                    "created_at": now_iso,
                }
                d.setdefault("cards", []).append(card)
                d["updated_at"] = now_iso
                found = card
                break
        if not found:
            raise LearningServiceError(f"Deck not found: {deck_id}")
        self._write_jsonl(self.decks_file, decks)
        return found

    @_locked
    def add_cards(self, deck_id: str, cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Append many cards in one read-modify-write; all or nothing."""
        clean = []
        for c in cards:
            front, back = str(c.get("front", "")).strip(), str(c.get("back", "")).strip()
            if not front or not back:
                raise LearningValidationError("A card needs both a front and a back")
            clean.append((front, back, c))
        decks = self._read_jsonl(self.decks_file)
        deck = next((d for d in decks if d.get("id") == deck_id), None)
        if deck is None:
            raise LearningServiceError(f"Deck not found: {deck_id}")
        now_iso = datetime.now(timezone.utc).isoformat()
        added = []
        for front, back, c in clean:
            added.append({
                "id": f"card_{uuid.uuid4().hex}",
                "front": front,
                "back": back,
                "hint": str(c.get("hint") or "").strip(),
                "explanation": str(c.get("explanation") or "").strip(),
                "tags": c.get("tags") or [],
                "srs": initial_srs_state(),
                "created_at": now_iso,
            })
        deck.setdefault("cards", []).extend(added)
        deck["updated_at"] = now_iso
        self._write_jsonl(self.decks_file, decks)
        return added

    @_locked
    def delete_card(self, deck_id: str, card_id: str) -> None:
        decks = self._read_jsonl(self.decks_file)
        found = False
        for d in decks:
            if d.get("id") == deck_id:
                cards = d.get("cards", [])
                filtered = [c for c in cards if c.get("id") != card_id]
                if len(filtered) != len(cards):
                    d["cards"] = filtered
                    d["updated_at"] = datetime.now(timezone.utc).isoformat()
                    found = True
                    break
        if not found:
            raise LearningServiceError(f"Card {card_id} or Deck {deck_id} not found")
        self._write_jsonl(self.decks_file, decks)

    @_locked
    def get_due_cards(self, deck_id: Optional[str] = None, limit: Optional[int] = None) -> list[dict[str, Any]]:
        decks = self._read_jsonl(self.decks_file)
        now_iso = datetime.now(timezone.utc).isoformat()
        due_cards = []
        for d in decks:
            if deck_id and d.get("id") != deck_id:
                continue
            for c in d.get("cards", []):
                srs = c.get("srs", {})
                next_rev = srs.get("next_review")
                if not next_rev or next_rev <= now_iso:
                    due_cards.append({
                        **c,
                        "deck_id": d.get("id"),
                        "deck_title": d.get("title"),
                        "course_name": d.get("course_name"),
                    })
        if limit is not None and limit >= 0:
            # most overdue first, so a capped session still clears the oldest backlog
            due_cards.sort(key=lambda c: (c.get("srs") or {}).get("next_review") or "")
            return due_cards[:limit]
        return due_cards

    @_locked
    def submit_card_review(self, deck_id: str, card_id: str, rating: Rating) -> dict[str, Any]:
        decks = self._read_jsonl(self.decks_file)
        updated_card = None
        for d in decks:
            if d.get("id") == deck_id:
                for c in d.get("cards", []):
                    if c.get("id") == card_id:
                        srs = c.get("srs", initial_srs_state())
                        new_srs = calculate_next_review(
                            rating=rating,
                            current_ease=srs.get("ease_factor", 2.5),
                            repetition=srs.get("repetition", 0),
                            interval_days=srs.get("interval_days", 0),
                            lapses=srs.get("lapses", 0),
                        )
                        c["srs"] = new_srs
                        d["updated_at"] = datetime.now(timezone.utc).isoformat()
                        updated_card = c
                        break
        if not updated_card:
            raise LearningServiceError(f"Card {card_id} not found in deck {deck_id}")
        self._write_jsonl(self.decks_file, decks)
        return updated_card

    # ── Quizzes & Assessments ──────────────────────────────────────────
    @_locked
    def list_quizzes(self, course_id: Optional[str] = None) -> list[dict[str, Any]]:
        quizzes = self._read_jsonl(self.quizzes_file)
        if course_id:
            return [q for q in quizzes if q.get("course_id") == course_id]
        return quizzes

    @_locked
    def get_quiz(self, quiz_id: str) -> dict[str, Any]:
        quizzes = self._read_jsonl(self.quizzes_file)
        for q in quizzes:
            if q.get("id") == quiz_id:
                return q
        raise LearningServiceError(f"Quiz not found: {quiz_id}")

    @_locked
    def create_quiz(
        self,
        title: str,
        topic: str,
        course_id: Optional[str] = None,
        course_name: Optional[str] = None,
        questions: Optional[list[dict[str, Any]]] = None,
        time_limit_mins: int = 15,
    ) -> dict[str, Any]:
        quizzes = self._read_jsonl(self.quizzes_file)
        quiz_id = f"quiz_{uuid.uuid4().hex[:8]}"
        now_iso = datetime.now(timezone.utc).isoformat()

        formatted_questions = []
        if questions:
            for q in questions:
                q_id = q.get("id") or f"q_{uuid.uuid4().hex[:8]}"
                formatted_questions.append({
                    "id": q_id,
                    "prompt": q.get("prompt", ""),
                    "type": q.get("type", "multiple_choice"),  # multiple_choice, true_false, short_answer
                    "options": q.get("options", []),
                    "correct_answer": q.get("correct_answer", ""),
                    "explanation": q.get("explanation", ""),
                    "concept": (q.get("concept") or "").strip() or topic.strip(),
                })

        new_quiz = {
            "id": quiz_id,
            "title": title.strip(),
            "topic": topic.strip(),
            "course_id": course_id,
            "course_name": course_name,
            "time_limit_mins": time_limit_mins,
            "questions": formatted_questions,
            "attempts": [],
            "best_score": None,
            "created_at": now_iso,
            "updated_at": now_iso,
        }
        quizzes.insert(0, new_quiz)
        self._write_jsonl(self.quizzes_file, quizzes)
        return new_quiz

    @_locked
    def delete_quiz(self, quiz_id: str) -> None:
        quizzes = self._read_jsonl(self.quizzes_file)
        new_quizzes = [q for q in quizzes if q.get("id") != quiz_id]
        if len(new_quizzes) == len(quizzes):
            raise LearningServiceError(f"Quiz not found: {quiz_id}")
        self._write_jsonl(self.quizzes_file, new_quizzes)

    @_locked
    def submit_quiz_attempt(
        self,
        quiz_id: str,
        answers: dict[str, Any],  # { question_id: user_answer }
        time_spent_secs: int = 0,
    ) -> dict[str, Any]:
        quizzes = self._read_jsonl(self.quizzes_file)
        target = None
        for q in quizzes:
            if q.get("id") == quiz_id:
                target = q
                break
        if not target:
            raise LearningServiceError(f"Quiz not found: {quiz_id}")

        questions = target.get("questions", [])
        total_q = len(questions)
        correct_count = 0
        breakdown = []
        now_iso = datetime.now(timezone.utc).isoformat()

        for question in questions:
            qid = question.get("id")
            user_ans = answers.get(qid)
            correct_ans = question.get("correct_answer")
            is_correct = False

            if user_ans is not None:
                # normalize strings
                if isinstance(user_ans, str) and isinstance(correct_ans, str):
                    is_correct = user_ans.strip().lower() == correct_ans.strip().lower()
                else:
                    is_correct = user_ans == correct_ans

            if is_correct:
                correct_count += 1

            breakdown.append({
                "question_id": qid,
                "prompt": question.get("prompt"),
                "user_answer": user_ans,
                "correct_answer": correct_ans,
                "is_correct": is_correct,
                "explanation": question.get("explanation"),
                "concept": question.get("concept"),
            })

            # Update topic mastery automatically (older quizzes may hold an empty concept)
            concept = (question.get("concept") or "").strip() or (target.get("topic") or "").strip()
            if concept:
                self.record_topic_result(
                    topic=concept,
                    course_id=target.get("course_id"),
                    course_name=target.get("course_name"),
                    is_correct=is_correct,
                )

        score_percent = round((correct_count / max(1, total_q)) * 100, 1)

        attempt = {
            "attempt_id": f"att_{uuid.uuid4().hex[:8]}",
            "score": score_percent,
            "correct_count": correct_count,
            "total_questions": total_q,
            "time_spent_secs": time_spent_secs,
            "breakdown": breakdown,
            "completed_at": now_iso,
        }

        target.setdefault("attempts", []).append(attempt)
        current_best = target.get("best_score")
        target["best_score"] = max(score_percent, current_best if current_best is not None else 0)
        target["updated_at"] = now_iso
        self._write_jsonl(self.quizzes_file, quizzes)

        return attempt

    # ── Concept Mastery Matrix ─────────────────────────────────────────
    @_locked
    def get_mastery_matrix(self) -> dict[str, Any]:
        default_data = {"topics": [], "overall_mastery": 0}
        data = self._read_json(self.mastery_file, default_data)
        topics = data.get("topics", [])
        if topics:
            status_weights = {"needs_review": 25, "developing": 50, "proficient": 75, "mastered": 100}
            total_points = sum(status_weights.get(t.get("status", "developing"), 50) for t in topics)
            data["overall_mastery"] = round(total_points / len(topics))
        return data

    @_locked
    def record_topic_result(self, topic: str, course_id: Optional[str], course_name: Optional[str], is_correct: bool) -> None:
        data = self.get_mastery_matrix()
        topics = data.get("topics", [])
        now_iso = datetime.now(timezone.utc).isoformat()
        clean_topic = topic.strip()

        target = None
        for t in topics:
            if t.get("name", "").lower() == clean_topic.lower() and (not course_id or t.get("course_id") == course_id):
                target = t
                break

        if not target:
            target = {
                "id": f"top_{uuid.uuid4().hex[:8]}",
                "name": clean_topic,
                "course_id": course_id,
                "course_name": course_name or "General",
                "status": "proficient" if is_correct else "developing",
                "attempts_count": 0,
                "correct_count": 0,
                "last_practiced": now_iso,
            }
            topics.append(target)

        target["attempts_count"] = target.get("attempts_count", 0) + 1
        if is_correct:
            target["correct_count"] = target.get("correct_count", 0) + 1
        target["last_practiced"] = now_iso

        # A status the user set by hand holds until 3 quiz answers have come in since.
        if target.get("manual_status"):
            since = target["attempts_count"] - target.get("manual_at_attempts", 0)
            if since < 3:
                data["topics"] = topics
                self._write_json(self.mastery_file, data)
                return
            target["manual_status"] = False

        # calculate status from accuracy
        acc = target["correct_count"] / target["attempts_count"]
        if target["attempts_count"] >= 3:
            if acc >= 0.85:
                target["status"] = "mastered"
            elif acc >= 0.65:
                target["status"] = "proficient"
            elif acc >= 0.4:
                target["status"] = "developing"
            else:
                target["status"] = "needs_review"
        else:
            target["status"] = "proficient" if is_correct else "developing"

        data["topics"] = topics
        self._write_json(self.mastery_file, data)

    @_locked
    def set_topic_status(self, topic_id: str, status: str) -> dict[str, Any]:
        if status not in ["needs_review", "developing", "proficient", "mastered"]:
            raise LearningServiceError("Invalid status")
        data = self.get_mastery_matrix()
        topics = data.get("topics", [])
        found = None
        for t in topics:
            if t.get("id") == topic_id:
                t["status"] = status
                t["manual_status"] = True
                t["manual_at_attempts"] = t.get("attempts_count", 0)
                t["last_practiced"] = datetime.now(timezone.utc).isoformat()
                found = t
                break
        if not found:
            raise LearningServiceError(f"Topic {topic_id} not found")
        data["topics"] = topics
        self._write_json(self.mastery_file, data)
        return found

    @_locked
    def add_topic(self, name: str, course_id: Optional[str] = None, course_name: Optional[str] = None, status: str = "developing") -> dict[str, Any]:
        data = self.get_mastery_matrix()
        topics = data.get("topics", [])
        now_iso = datetime.now(timezone.utc).isoformat()
        topic = {
            "id": f"top_{uuid.uuid4().hex[:8]}",
            "name": name.strip(),
            "course_id": course_id,
            "course_name": course_name or "General",
            "status": status,
            "attempts_count": 0,
            "correct_count": 0,
            "last_practiced": now_iso,
        }
        if status != "developing":
            topic["manual_status"] = True
            topic["manual_at_attempts"] = 0
        topics.append(topic)
        data["topics"] = topics
        self._write_json(self.mastery_file, data)
        return topic

    # ── High-Yield Study Guides ────────────────────────────────────────
    @_locked
    def list_guides(self, course_id: Optional[str] = None) -> list[dict[str, Any]]:
        guides = self._read_jsonl(self.guides_file)
        if course_id:
            return [g for g in guides if g.get("course_id") == course_id]
        return guides

    @_locked
    def get_guide(self, guide_id: str) -> dict[str, Any]:
        guides = self._read_jsonl(self.guides_file)
        for g in guides:
            if g.get("id") == guide_id:
                return g
        raise LearningServiceError(f"Study guide not found: {guide_id}")

    @_locked
    def create_guide(
        self,
        title: str,
        topic: str,
        content: str,
        course_id: Optional[str] = None,
        course_name: Optional[str] = None,
        key_takeaways: Optional[list[str]] = None,
        formulas: Optional[list[str]] = None,
        tags: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        guides = self._read_jsonl(self.guides_file)
        guide_id = f"guide_{uuid.uuid4().hex[:8]}"
        now_iso = datetime.now(timezone.utc).isoformat()
        guide = {
            "id": guide_id,
            "title": title.strip(),
            "topic": topic.strip(),
            "content": content.strip(),
            "course_id": course_id,
            "course_name": course_name,
            "key_takeaways": key_takeaways or [],
            "formulas": formulas or [],
            "tags": tags or [],
            "created_at": now_iso,
            "updated_at": now_iso,
        }
        guides.insert(0, guide)
        self._write_jsonl(self.guides_file, guides)
        return guide

    @_locked
    def delete_guide(self, guide_id: str) -> None:
        guides = self._read_jsonl(self.guides_file)
        new_guides = [g for g in guides if g.get("id") != guide_id]
        if len(new_guides) == len(guides):
            raise LearningServiceError(f"Guide not found: {guide_id}")
        self._write_jsonl(self.guides_file, new_guides)

    # ── Deep Work & Focus Sessions ─────────────────────────────────────
    @_locked
    def list_focus_sessions(self) -> list[dict[str, Any]]:
        return self._read_jsonl(self.focus_file)

    @_locked
    def log_focus_session(
        self,
        duration_minutes: int,
        topic: str,
        goal: str = "",
        reflections: str = "",
        course_id: Optional[str] = None,
        course_name: Optional[str] = None,
    ) -> dict[str, Any]:
        if not (0 < duration_minutes <= 1440):
            raise LearningValidationError("duration_minutes must be between 1 and 1440")
        sessions = self._read_jsonl(self.focus_file)
        session_id = f"focus_{uuid.uuid4().hex[:8]}"
        now_iso = datetime.now(timezone.utc).isoformat()
        session = {
            "id": session_id,
            "duration_minutes": duration_minutes,
            "topic": topic.strip(),
            "goal": goal.strip(),
            "reflections": reflections.strip(),
            "course_id": course_id,
            "course_name": course_name,
            "completed_at": now_iso,
        }
        sessions.insert(0, session)
        self._write_jsonl(self.focus_file, sessions)
        return session

    # ── Overview & Aggregated Analytics ────────────────────────────────
    @_locked
    def get_overview(self) -> dict[str, Any]:
        decks = self.list_decks()
        quizzes = self.list_quizzes()
        mastery = self.get_mastery_matrix()
        focus = self.list_focus_sessions()

        now_iso = datetime.now(timezone.utc).isoformat()
        total_cards = sum(d.get("total_cards", 0) for d in decks)
        cards_due = sum(d.get("due_cards", 0) for d in decks)

        total_quizzes = len(quizzes)
        all_attempts = [att for q in quizzes for att in q.get("attempts", [])]
        avg_quiz_score = round(sum(att.get("score", 0) for att in all_attempts) / max(1, len(all_attempts)), 1) if all_attempts else 0

        total_focus_mins = sum(s.get("duration_minutes", 0) for s in focus)

        return {
            "cards_due_today": cards_due,
            "total_cards": total_cards,
            "total_decks": len(decks),
            "total_quizzes": total_quizzes,
            "quiz_attempts_count": len(all_attempts),
            "avg_quiz_score": avg_quiz_score,
            "overall_mastery": mastery.get("overall_mastery", 0),
            "total_topics": len(mastery.get("topics", [])),
            "total_focus_minutes": total_focus_mins,
            "recent_focus_sessions": focus[:5],
        }
