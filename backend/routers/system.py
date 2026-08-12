"""System conveniences: folder backup + start-at-login."""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from backend.services import backup, login_launch

router = APIRouter(prefix="/api/system", tags=["system"])


class BackupBody(BaseModel):
    path: str = ""


class AutostartBody(BaseModel):
    enabled: bool


@router.get("/backup")
def backup_status() -> dict:
    return backup.status()


@router.post("/backup/config")
def backup_config(body: BackupBody) -> dict:
    return backup.set_path(body.path)


@router.post("/backup/now")
def backup_now() -> dict:
    return backup.run_backup()


@router.get("/autostart")
def autostart_status() -> dict:
    return {"enabled": login_launch.enabled()}


@router.post("/autostart")
def autostart_set(body: AutostartBody) -> dict:
    return login_launch.enable() if body.enabled else login_launch.disable()
