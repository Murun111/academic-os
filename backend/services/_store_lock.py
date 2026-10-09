"""Shared write-lock + unique tmp names for the JSONL stores.

Read-modify-write on a JSONL file (update/delete rewrite, add appends) must be
serialised: sync endpoints, the Canvas auto-sync loop and the request
threadpool all write concurrently, and unserialised writers lose each other's
changes. The lock is keyed by file path, so every service instance pointing
at the same data dir shares it.
"""
from __future__ import annotations

import os
import threading
import uuid
from pathlib import Path

_guard = threading.Lock()
_locks: dict[str, threading.RLock] = {}


def lock_for(path: Path) -> threading.RLock:
    key = os.path.realpath(path)
    with _guard:
        lk = _locks.get(key)
        if lk is None:
            lk = _locks[key] = threading.RLock()
        return lk


def unique_tmp(path: Path) -> Path:
    """A per-write tmp file next to *path* (never shared between writers)."""
    return path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
