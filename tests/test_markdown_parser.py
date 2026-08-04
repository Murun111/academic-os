"""Tests for backend.markdown_parser."""
import pytest

from backend.markdown_parser import (
    extract_wikilinks,
    parse_frontmatter,
    strip_frontmatter,
    Wikilink,
)


# === parse_frontmatter ===

def test_parses_simple_frontmatter():
    text = """---
type: project
status: active
last_updated: 2026-06-11
---

# Title
body
"""
    fm, body = parse_frontmatter(text)
    assert fm["type"] == "project"
    assert fm["status"] == "active"
    assert "Title" in body
    assert "---" not in body[:50]


def test_no_frontmatter_returns_empty():
    fm, body = parse_frontmatter("just a body\nwith two lines")
    assert fm == {}
    assert "just a body" in body


def test_frontmatter_with_lists():
    text = """---
type: concept
sources:
  - "raw/notes/foo.md"
  - "Ascent Studios Co/Website.md"
---
body
"""
    fm, body = parse_frontmatter(text)
    assert fm["type"] == "concept"
    assert fm["sources"] == ["raw/notes/foo.md", "Ascent Studios Co/Website.md"]


def test_frontmatter_with_special_chars_in_values():
    """Quotes, colons, special chars inside string values must survive."""
    text = """---
title: "ImprovOS: the modular platform"
description: "build a 3–5 day client build"
---
body
"""
    fm, _ = parse_frontmatter(text)
    assert fm["title"] == "ImprovOS: the modular platform"
    assert "3–5" in fm["description"]


def test_strip_frontmatter_removes_delimiters():
    text = """---
key: val
---
body
"""
    out = strip_frontmatter(text)
    assert not out.startswith("---")
    assert "body" in out


# === extract_wikilinks ===

def test_extracts_simple_wikilink():
    text = "see [[wiki/projects/parvis-ai|Parvis Ai]] for details"
    links = extract_wikilinks(text)
    assert len(links) == 1
    assert links[0].target == "wiki/projects/parvis-ai"
    assert links[0].label == "Parvis Ai"


def test_extracts_multiple_wikilinks():
    text = "linked to [[a]] and [[b/c|the C page]] and [[d]]"
    links = extract_wikilinks(text)
    assert len(links) == 3
    assert links[0].target == "a"
    assert links[0].label == "a"  # no alias = target as label
    assert links[1].target == "b/c"
    assert links[1].label == "the C page"
    assert links[2].target == "d"


def test_no_wikilinks_returns_empty():
    text = "this text has no links at all"
    assert extract_wikilinks(text) == []


def test_wikilink_in_code_block_is_excluded():
    """Wikilinks inside ```fenced``` blocks should not be extracted (per the
    vault's existing convention). The dashboard's graph only shows real links."""
    text = """```
this is code with [[fake-link]] that should not count
```

real [[actual-link]] here
"""
    links = extract_wikilinks(text)
    assert len(links) == 1
    assert links[0].target == "actual-link"


def test_wikilink_in_inline_code_is_excluded():
    text = "use the `[[template]]` syntax in your notes — but `[[real]]` should not count"
    links = extract_wikilinks(text)
    assert links == []


def test_wikilink_in_anchor_only():
    text = "see [[Page Name]] for the full overview"
    links = extract_wikilinks(text)
    assert links[0].target == "Page Name"
    assert links[0].label == "Page Name"


def test_wikilink_with_path():
    """Wikilinks can include /path/to/note.md or /path/to/note (Obsidian-style)."""
    text = "linked: [[wiki/projects/parvis-ai.md|Parvis]]"
    links = extract_wikilinks(text)
    assert links[0].target == "wiki/projects/parvis-ai.md"
    assert links[0].label == "Parvis"


def test_wikilink_position_is_tracked():
    text = "before [[link1]] middle [[link2]] after"
    # 'before ' (7) + '[[link1]]' (9) + ' middle ' (8) = position 24 for '[[link2]]'
    links = extract_wikilinks(text)
    assert len(links) == 2
    assert links[0].position == 7
    assert links[1].position == 24


# === Wikilink dataclass ===

def test_wikilink_strips_md_extension_for_lookup():
    """A wikilink to 'foo.md' should look up the same as 'foo' (Obsidian behavior)."""
    link = Wikilink(target="wiki/projects/parvis-ai.md", label="Parvis", position=0)
    assert link.lookup_key() == "wiki/projects/parvis-ai"
