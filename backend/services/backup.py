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


def _backup_dir() -> Path | None:
    """Configured `<path>/AcademicOS-Backup`, or None if unset/missing."""
    path = config().get("path") or ""
    if not path:
        return None
    dest = Path(path) / "AcademicOS-Backup"
    if not dest.is_dir():
        return None
    return dest


def _mirrored_files(base: Path) -> dict[str, Path]:
    """Map of root-relative posix path -> absolute Path for every file under base's mirrored subdirs."""
    files: dict[str, Path] = {}
    for sub in _SUBDIRS:
        sub_dir = base / sub
        if not sub_dir.exists():
            continue
        for p in sub_dir.rglob("*"):
            if p.is_file():
                files[p.relative_to(base).as_posix()] = p
    return files


def _diff_backup_live(dest: Path, root: Path) -> tuple[dict[str, Path], dict[str, Path], dict[str, Path]]:
    """(add, overwrite, delete) file maps comparing backup `dest` against live `root`."""
    backup_files = _mirrored_files(dest)
    live_files = _mirrored_files(root)
    add = {rel: p for rel, p in backup_files.items() if rel not in live_files}
    overwrite = {}
    for rel, bpath in backup_files.items():
        lpath = live_files.get(rel)
        if lpath is None:
            continue
        bstat, lstat = bpath.stat(), lpath.stat()
        if bstat.st_size != lstat.st_size or int(bstat.st_mtime) != int(lstat.st_mtime):
            overwrite[rel] = bpath
    delete = {rel: p for rel, p in live_files.items() if rel not in backup_files}
    return add, overwrite, delete


def _prune_snapshots(snap_root: Path, keep: int = 3) -> None:
    if not snap_root.exists():
        return
    snapshots = sorted((p for p in snap_root.iterdir() if p.is_dir()), key=lambda p: p.name, reverse=True)
    for old in snapshots[keep:]:
        shutil.rmtree(old, ignore_errors=True)


def preview_restore() -> dict:
    """Compare the configured backup mirror against the live data root."""
    dest = _backup_dir()
    if dest is None:
        return {
            "ok": False,
            "error": "no_backup_found",
            "backup_dir": None,
            "counts": {"add": 0, "overwrite": 0, "delete": 0},
            "add": [],
            "overwrite": [],
            "delete": [],
        }
    add, overwrite, delete = _diff_backup_live(dest, _root())
    return {
        "ok": True,
        "error": None,
        "backup_dir": str(dest),
        "counts": {"add": len(add), "overwrite": len(overwrite), "delete": len(delete)},
        "add": sorted(add)[:20],
        "overwrite": sorted(overwrite)[:20],
        "delete": sorted(delete)[:20],
    }


def run_restore() -> dict:
    """Snapshot the live mirrored dirs, then mirror the backup back over them."""
    dest = _backup_dir()
    if dest is None:
        return {"ok": False, "error": "no_backup_found", "restored": 0, "deleted": 0, "snapshot": None}
    root = _root()
    try:
        snap_root = root / "pre-restore-snapshots"
        snap_dir = snap_root / datetime.now().strftime("%Y%m%d-%H%M%S")
        snap_dir.mkdir(parents=True, exist_ok=True)
        for sub in _SUBDIRS:
            src = root / sub
            if src.exists():
                shutil.copytree(src, snap_dir / sub, dirs_exist_ok=True)
        _prune_snapshots(snap_root)

        add, overwrite, delete = _diff_backup_live(dest, root)

        restored = 0
        for rel, bpath in {**add, **overwrite}.items():
            live_path = root / rel
            live_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(bpath, live_path)
            restored += 1

        deleted = 0
        for rel in delete:
            (root / rel).unlink(missing_ok=True)
            deleted += 1

        return {"ok": True, "error": None, "restored": restored, "deleted": deleted, "snapshot": str(snap_dir)}
    except OSError as e:
        return {"ok": False, "error": str(e), "restored": 0, "deleted": 0, "snapshot": None}
