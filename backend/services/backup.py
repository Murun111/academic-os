"""Folder backup — one setting that makes laptop death survivable.

The student picks any folder (iCloud Drive, Google Drive, Dropbox — they all
mount as folders) and the app mirrors its data there: data/, notes/, agents/.
The models/ dir is deliberately excluded (gigabytes, re-downloadable).

Config: data/backup.json {"path": "...", "last_backup": iso}
Loop: hourly while the app runs, plus a Back Up Now button.
"""
from __future__ import annotations

import asyncio
import json
import shutil
from datetime import datetime
from pathlib import Path

BACKUP_INTERVAL_SECONDS = 60 * 60
_SUBDIRS = ("data", "notes", "agents")  # what gets mirrored


def _root() -> Path:
    from backend.vault import agentic_os_dir
    return agentic_os_dir()


def _config_path() -> Path:
    d = _root() / "data"
    d.mkdir(parents=True, exist_ok=True)
    return d / "backup.json"


def config() -> dict:
    p = _config_path()
    if p.exists():
        try:
            return json.loads(p.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {"path": "", "last_backup": None}


def _save(cfg: dict) -> None:
    _config_path().write_text(json.dumps(cfg))


def set_path(path: str) -> dict:
    """Set (or clear, with "") the backup destination folder."""
    path = (path or "").strip()
    if path:
        target = Path(path).expanduser()
        try:
            target.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            return {"error": f"cannot create folder: {e}"}
        if not target.is_dir():
            return {"error": "not a folder"}
        path = str(target)
    cfg = config()
    cfg["path"] = path
    _save(cfg)
    return status()


def run_backup() -> dict:
    """Mirror data/, notes/, agents/ into <path>/AcademicOS-Backup."""
    cfg = config()
    path = cfg.get("path") or ""
    if not path:
        return {"error": "no backup folder set"}
    dest = Path(path) / "AcademicOS-Backup"
    root = _root()
    try:
        dest.mkdir(parents=True, exist_ok=True)
        copied = 0
        for sub in _SUBDIRS:
            src = root / sub
            if not src.exists():
                continue
            shutil.copytree(src, dest / sub, dirs_exist_ok=True)
            copied += 1
        cfg["last_backup"] = datetime.now().isoformat(timespec="seconds")
        _save(cfg)
        return {"ok": True, "dest": str(dest), "last_backup": cfg["last_backup"]}
    except OSError as e:
        return {"error": str(e)}


def status() -> dict:
    cfg = config()
    return {"path": cfg.get("path") or "", "last_backup": cfg.get("last_backup")}


async def backup_loop() -> None:
    """Hourly mirror while the app runs; silent when no folder is set."""
    await asyncio.sleep(120)
    while True:
        try:
            if config().get("path"):
                result = run_backup()
                if result.get("ok"):
                    print(f"[backup] mirrored to {result['dest']}")
                else:
                    print(f"[backup] failed: {result.get('error')}")
        except Exception as e:  # noqa: BLE001
            print(f"[backup] crashed: {e!r}")
        await asyncio.sleep(BACKUP_INTERVAL_SECONDS)
