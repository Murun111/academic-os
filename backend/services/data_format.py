"""Data format version stamp — refuses writes from an older app onto newer data.

Every service in `backend/services/` deserializes JSONL records through a
defensive `from_dict` that silently drops any field it doesn't recognize
(`{k: v for k, v in d.items() if k in allowed}`). That's safe for forward
compatibility, but it means: if a newer app version writes a record with an
extra field, and an older app version then reads and rewrites that same
record, the extra field is gone with no error and no log line. This stamp
lets the app detect "the data on disk is newer than the code reading it"
before that silent loss happens, so it can refuse to write instead.

Stamp file: data/format.json under the data root, e.g.
    {"format_version": 1, "app_version": "0.4.2", "stamped_at": "2026-08-12T09:00:00+00:00"}
"""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

CURRENT_FORMAT = 1


def stamp_path() -> Path:
    """Return <data_root>/data/format.json, creating the parent dir if needed."""
    from backend.vault import agentic_os_dir

    d = agentic_os_dir() / "data"
    d.mkdir(parents=True, exist_ok=True)
    return d / "format.json"


def read_stamp() -> dict | None:
    """Return the parsed stamp, or None if it's missing or corrupt."""
    p = stamp_path()
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def _write_stamp(data: dict) -> None:
    """Write the stamp atomically: tmp file in the same dir, then replace."""
    p = stamp_path()
    tmp = p.with_name(f".{p.name}.{uuid.uuid4().hex}.tmp")
    tmp.write_text(json.dumps(data, indent=2))
    os.replace(tmp, p)


def ensure_stamp(app_version: str) -> dict:
    """Ensure the format stamp exists and is compatible with CURRENT_FORMAT.

    - Missing or corrupt stamp: write a fresh one and report compatible.
    - Found version <= CURRENT_FORMAT: rewrite the stamp with current values
      (bumps app_version/stamped_at), compatible True.
    - Found version > CURRENT_FORMAT: leave the file untouched and report
      compatible False — this app is older than the data on disk.
    """
    existing = read_stamp()
    found = existing.get("format_version") if existing else None

    if found is not None and found > CURRENT_FORMAT:
        return {"found": found, "current": CURRENT_FORMAT, "compatible": False}

    _write_stamp(
        {
            "format_version": CURRENT_FORMAT,
            "app_version": app_version,
            "stamped_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    return {"found": found, "current": CURRENT_FORMAT, "compatible": True}
