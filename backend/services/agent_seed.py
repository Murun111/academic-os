"""Seed default agents into an empty data root.

The DMG bundles examples/agents/*.md (deadline-watcher, scholarship-scout),
but a fresh install has an empty <root>/agents/ — so the Assistants page
showed nothing until someone copied the files by hand. On startup, if the
agents dir has no .md files, copy the bundled defaults in. Never overwrites:
a dir with any .md file is left exactly as the user has it.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path


def bundled_agents_dir() -> Path | None:
    """Locate the shipped examples/agents dir: frozen bundle first, then repo."""
    candidates = []
    if getattr(sys, "frozen", False):
        candidates.append(Path(sys.executable).parent / "_internal" / "examples" / "agents")
        candidates.append(Path(sys.executable).parent / "examples" / "agents")
    candidates.append(Path(__file__).resolve().parent.parent.parent / "examples" / "agents")
    for c in candidates:
        if c.is_dir() and any(c.glob("*.md")):
            return c
    return None


def seed_default_agents() -> int:
    """Copy bundled agent files into <root>/agents/ if it has none. Returns
    the number of files copied (0 = already populated or nothing bundled)."""
    from backend.vault import agentic_os_dir

    target = agentic_os_dir() / "agents"
    target.mkdir(parents=True, exist_ok=True)
    if any(target.glob("*.md")):
        return 0
    src = bundled_agents_dir()
    if src is None:
        return 0
    copied = 0
    for f in sorted(src.glob("*.md")):
        shutil.copy2(f, target / f.name)
        copied += 1
    return copied
