"""Student profile — the stage (highschool/undergrad/grad/beyond) that
drives stage-aware UI, plus the optional post-undergrad track (pre-med,
pre-law, …) and exam date. Stored as a single JSON file in the data root."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Literal, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/profile", tags=["profile"])

Stage = Literal["highschool", "undergrad", "gapyear", "grad", "beyond"]
Track = Literal["premed", "prelaw", "predental", "gradschool", "unsure"]


class ProfileBody(BaseModel):
    stage: Stage
    name: str = ""
    track: Optional[Track] = None
    test_date: str = ""  # ISO date of the entrance exam, or empty
    reminders: bool = True  # daily deadline notification toggle


def _path() -> Path:
    from backend.vault import agentic_os_dir
    d = agentic_os_dir() / "data"
    d.mkdir(parents=True, exist_ok=True)
    return d / "profile.json"


@router.get("")
def get_profile() -> dict:
    """Current profile; stage is null until onboarding sets it."""
    p = _path()
    if p.exists():
        try:
            data = json.loads(p.read_text())
            return {
                "stage": data.get("stage"),
                "name": data.get("name", ""),
                "track": data.get("track"),
                "test_date": data.get("test_date", ""),
                "reminders": bool(data.get("reminders", True)),
            }
        except (json.JSONDecodeError, OSError):
            pass
    return {"stage": None, "name": "", "track": None, "test_date": "", "reminders": True}


@router.put("")
def put_profile(body: ProfileBody) -> dict:
    """Replace the profile: stage (validated enum), name, track, exam date."""
    if body.test_date:
        try:
            date.fromisoformat(body.test_date)
        except ValueError:
            raise HTTPException(status_code=422, detail="test_date must be an ISO date (YYYY-MM-DD)")
    p = _path()
    data = {
        "stage": body.stage,
        "name": body.name,
        "track": body.track,
        "test_date": body.test_date,
        "reminders": body.reminders,
    }
    p.write_text(json.dumps(data))
    return {"ok": True, **data}


@router.post("/reminders/test")
def test_reminder() -> dict:
    """Fire today's deadline notification now (Settings test button)."""
    from backend.services.deadline_reminders import check_and_send
    return check_and_send(force=True)
