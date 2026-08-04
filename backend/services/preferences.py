"""Preference logging — the raw training data for a future reward/preference model.

Every accept / reject / correction the translator produces is a labeled example
of "what counts as a good translation". This is the passive data tap that, once
enough accumulates, makes the first *trained* model (a preference model, the gate
for best-of-N and the eventual LoRA) possible. Append-only JSONL, fail-open.

Labels:
  - "correction": you edited a machine translation → (chosen=your fix, rejected=machine).
  - "auto_accept": the self-scoring loop kept a translation (weak positive).
  - "auto_flag":   the self-scoring loop flagged one for review (weak negative).
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from backend.vault import agentic_os_dir


def _default_path() -> Path:
    return agentic_os_dir() / "data" / "kb" / "preferences.jsonl"


def log_preference(*, source: str, direction: str, label: str,
                   chosen: str = "", rejected: str = "",
                   score: Optional[float] = None, meta: Optional[dict] = None,
                   path: Optional[Path] = None) -> bool:
    """Append one labeled preference example. Returns True on success. Never raises."""
    try:
        p = Path(path) if path else _default_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        rec = {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "source": source, "direction": direction, "label": label,
            "chosen": chosen, "rejected": rejected,
        }
        if score is not None:
            rec["score"] = round(float(score), 4)
        if meta:
            rec["meta"] = meta
        with p.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        return True
    except (OSError, ValueError, TypeError):
        return False  # logging must never break translation


def load_preferences(*, path: Optional[Path] = None) -> list[dict]:
    """Read all logged preference examples (tolerant of corrupt lines)."""
    p = Path(path) if path else _default_path()
    if not p.is_file():
        return []
    out: list[dict] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except (ValueError, json.JSONDecodeError):
            continue
    return out


def count(*, path: Optional[Path] = None) -> int:
    """How many preference examples exist — the readiness signal for training a
    reward model (rule of thumb: a few hundred corrections before it's worth it)."""
    return len(load_preferences(path=path))
