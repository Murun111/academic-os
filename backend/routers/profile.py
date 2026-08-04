"""Student profile — the stage (highschool/undergrad/grad/beyond) that
drives stage-aware UI. Stored as a single JSON file in the data root."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/api/profile", tags=["profile"])

Stage = Literal["highschool", "undergrad", "grad", "beyond"]


class ProfileBody(BaseModel):
    stage: Stage
    name: str = ""


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
            return {"stage": data.get("stage"), "name": data.get("name", "")}
        except (json.JSONDecodeError, OSError):
            pass
    return {"stage": None, "name": ""}


@router.put("")
def put_profile(body: ProfileBody) -> dict:
    """Set the stage (validated enum) and optional display name."""
    p = _path()
    p.write_text(json.dumps({"stage": body.stage, "name": body.name}))
    return {"ok": True, "stage": body.stage, "name": body.name}
