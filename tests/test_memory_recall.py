"""Tests for backend.services.memory_recall — Phase 1.4.

All tests run **offline** — memory_index.search is monkeypatched so no DB or
Ollama calls are made.
"""
from __future__ import annotations

import pytest

from backend.services.memory_types import MemoryItem
from backend.services.memory_recall import format_context, recall

_HEADER = (
    "[Memory — relevant context about the user."
    " Use if helpful; do not mention unless asked.]"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_item(
    kind: str = "fact",
    subject: str = "test subject",
    body: str = "test body",
) -> MemoryItem:
    return MemoryItem(kind=kind, subject=subject, body=body)


def _patch_search(monkeypatch, *, return_value: list | None = None, raise_exc: Exception | None = None) -> None:
    """Patch memory_index.search used inside memory_recall."""
    import backend.services.memory_index as idx

    if raise_exc is not None:
        exc = raise_exc

        def _search(query: str, k: int = 6) -> list:
            raise exc

        monkeypatch.setattr(idx, "search", _search)
    else:
        items = return_value if return_value is not None else []

        def _search(query: str, k: int = 6) -> list:
            return items

        monkeypatch.setattr(idx, "search", _search)


# ---------------------------------------------------------------------------
# recall() — empty / whitespace query
# ---------------------------------------------------------------------------

def test_empty_query_returns_empty(monkeypatch):
    _patch_search(monkeypatch, return_value=[])
    assert recall("") == ""


def test_whitespace_query_returns_empty(monkeypatch):
    _patch_search(monkeypatch, return_value=[])
    assert recall("   ") == ""


def test_newline_only_query_returns_empty(monkeypatch):
    _patch_search(monkeypatch, return_value=[])
    assert recall("\n\t") == ""


# ---------------------------------------------------------------------------
# recall() — no results
# ---------------------------------------------------------------------------

def test_no_results_returns_empty(monkeypatch):
    _patch_search(monkeypatch, return_value=[])
    assert recall("anything relevant") == ""


# ---------------------------------------------------------------------------
# recall() — search raises → no exception propagated
# ---------------------------------------------------------------------------

def test_search_raises_returns_empty_no_exception(monkeypatch):
    _patch_search(monkeypatch, raise_exc=RuntimeError("db error"))
    result = recall("query that triggers error")
    assert result == ""


def test_search_raises_value_error_returns_empty(monkeypatch):
    _patch_search(monkeypatch, raise_exc=ValueError("bad query"))
    assert recall("query") == ""


# ---------------------------------------------------------------------------
# format_context() — shape
# ---------------------------------------------------------------------------

def test_format_context_empty_list():
    assert format_context([]) == ""


def test_format_context_header_present():
    items = [_make_item()]
    result = format_context(items)
    assert result.startswith(_HEADER)


def test_format_context_one_bullet_per_item():
    items = [
        _make_item(kind="fact", subject="Subj A", body="Body A"),
        _make_item(kind="preference", subject="Subj B", body="Body B"),
    ]
    result = format_context(items)
    bullets = [ln for ln in result.split("\n") if ln.startswith("- ")]
    assert len(bullets) == 2


def test_format_context_bullet_format():
    """Each bullet must match ``- (<kind>) <subject> — <body>``."""
    items = [_make_item(kind="decision", subject="Memory spine first",
                        body="Phase 1.1 builds the write-back loop before new agents.")]
    result = format_context(items)
    expected = "- (decision) Memory spine first — Phase 1.1 builds the write-back loop before new agents."
    assert expected in result


def test_format_context_exact_shape():
    """Verify header and two bullets match the spec example exactly."""
    items = [
        _make_item(kind="decision", subject="Memory spine first",
                   body="Phase 1.1 builds the write-back loop before new agents."),
        _make_item(kind="preference", subject="Local-first models",
                   body="Use local Ollama LLMs by default."),
    ]
    lines = format_context(items).split("\n")
    assert lines[0] == _HEADER
    assert lines[1] == "- (decision) Memory spine first — Phase 1.1 builds the write-back loop before new agents."
    assert lines[2] == "- (preference) Local-first models — Use local Ollama LLMs by default."


def test_format_context_five_items_five_bullets():
    items = [_make_item(kind="fact", subject=f"S{i}", body=f"B{i}") for i in range(5)]
    result = format_context(items)
    bullets = [ln for ln in result.split("\n") if ln.startswith("- (")]
    assert len(bullets) == 5


# ---------------------------------------------------------------------------
# recall() — returns formatted block when within budget
# ---------------------------------------------------------------------------

def test_recall_returns_full_block_when_within_budget(monkeypatch):
    items = [_make_item(kind="fact", subject="Short", body="Short body.")]
    _patch_search(monkeypatch, return_value=items)
    result = recall("query", max_chars=1200)
    assert result == format_context(items)


def test_recall_result_starts_with_header(monkeypatch):
    items = [_make_item()]
    _patch_search(monkeypatch, return_value=items)
    result = recall("query")
    assert result.startswith(_HEADER)


# ---------------------------------------------------------------------------
# recall() — max_chars truncation
# ---------------------------------------------------------------------------

def test_max_chars_truncation_respects_limit(monkeypatch):
    """Output must never exceed max_chars."""
    long_body = "x" * 100
    items = [_make_item(kind="fact", subject=f"Subject {i}", body=long_body)
             for i in range(20)]
    _patch_search(monkeypatch, return_value=items)
    result = recall("query", max_chars=300)
    assert len(result) <= 300


def test_max_chars_no_partial_bullet(monkeypatch):
    """Every non-header line in the output must be a complete bullet."""
    long_body = "y" * 80
    items = [_make_item(kind="preference", subject=f"Pref {i}", body=long_body)
             for i in range(10)]
    _patch_search(monkeypatch, return_value=items)
    result = recall("query", max_chars=400)
    if not result:
        return  # empty is valid when nothing fits
    lines = result.split("\n")
    for line in lines[1:]:
        assert line.startswith("- ("), f"Partial or malformed bullet: {line!r}"


def test_max_chars_header_retained(monkeypatch):
    """The header must be the first line even when bullets are dropped."""
    long_body = "z" * 200  # each bullet ~220 chars; only header (~88) fits in 200
    items = [_make_item(kind="fact", subject=f"Subj {i}", body=long_body)
             for i in range(5)]
    _patch_search(monkeypatch, return_value=items)
    result = recall("query", max_chars=200)
    # Result may be header-only or empty if even header doesn't fit — but
    # header is 88 chars which is < 200, so it must be present.
    assert result != ""
    assert result.split("\n")[0] == _HEADER


def test_max_chars_whole_lines_only_combined(monkeypatch):
    """Combines all three truncation guarantees in one assertion."""
    body = "a" * 60
    items = [_make_item(kind="event", subject=f"Event {i}", body=body)
             for i in range(15)]
    _patch_search(monkeypatch, return_value=items)
    result = recall("query", max_chars=350)

    assert len(result) <= 350, "output exceeds max_chars"
    if result:
        lines = result.split("\n")
        assert lines[0] == _HEADER, "header not retained"
        for line in lines[1:]:
            assert line.startswith("- ("), f"partial bullet: {line!r}"
