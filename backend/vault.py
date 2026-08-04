"""Data-directory resolution.

Single source of truth for where Academic OS stores its state. Unlike
agentic-os (which was vault-first, writing into an Obsidian vault), the
fork keeps everything in a plain local data directory so students don't
need Obsidian or any prior setup.

Layout under the data root:
    data/           JSONL app state (applications, courses, tasks, documents, agents)
    agents/         agent spec markdown files (YAML frontmatter)
    notes/          free-form markdown the agent tools may read/write

The function names (resolve_vault_path / agentic_os_dir) are kept from the
fork source so existing services keep working; "vault" here just means the
data root.
"""
from __future__ import annotations

import os
from pathlib import Path

# Used when ACADEMIC_OS_DATA is unset.
_FALLBACK = Path.home() / ".academic-os"


def resolve_vault_path() -> Path:
    """Return the absolute path to the Academic OS data root, creating it
    if needed.

    Order of resolution:
    1. ACADEMIC_OS_DATA env var
    2. ~/.academic-os
    """
    raw = os.environ.get("ACADEMIC_OS_DATA")
    root = Path(raw).expanduser() if raw else _FALLBACK
    root.mkdir(parents=True, exist_ok=True)
    return root


def agentic_os_dir() -> Path:
    """Return the app-state root (kept name for compatibility with forked
    services, which append their own subpaths like data/inbox).

    Resolved on every call (not cached) so env changes are picked up.
    """
    return resolve_vault_path()


# Convenience for callers that don't need live re-resolution (most of them).
# Recomputed at import time.
AGENTIC_OS_DIR: Path = agentic_os_dir()
