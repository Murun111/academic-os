"""Tests for preference logging — the training data for a future reward model."""
from __future__ import annotations

from backend.services.preferences import count, load_preferences, log_preference


def test_log_and_load_roundtrip(tmp_path):
    p = tmp_path / "prefs.jsonl"
    assert log_preference(source="good morning", direction="en-mn", label="correction",
                          chosen="Өглөөний мэнд", rejected="uglunii mend", path=p)
    assert log_preference(source="water", direction="en-mn", label="auto_accept",
                          chosen="ус", score=0.8, path=p)
    prefs = load_preferences(path=p)
    assert len(prefs) == 2 and count(path=p) == 2
    corr = prefs[0]
    assert corr["label"] == "correction"
    assert corr["chosen"] == "Өглөөний мэнд" and corr["rejected"] == "uglunii mend"
    assert prefs[1]["score"] == 0.8


def test_load_missing_returns_empty(tmp_path):
    assert load_preferences(path=tmp_path / "nope.jsonl") == []
    assert count(path=tmp_path / "nope.jsonl") == 0


def test_corrupt_lines_tolerated(tmp_path):
    p = tmp_path / "prefs.jsonl"
    p.write_text('not json\n{"label":"ok","source":"a","direction":"en-mn"}\n', encoding="utf-8")
    prefs = load_preferences(path=p)
    assert len(prefs) == 1 and prefs[0]["label"] == "ok"

