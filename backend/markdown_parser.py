"""Markdown parsing helpers for the Obsidian vault.

Two responsibilities:
1. parse_frontmatter() — extract YAML frontmatter from a note, return
   (dict, body_after_frontmatter). The body still contains the H1 and
   subsequent content.

2. extract_wikilinks() — find all [[wiki-link]] references in the body,
   respecting Obsidian's conventions: alias syntax `[[target|label]]`,
   but skipping wikilinks inside fenced code blocks or inline code.

The vault's existing CLAUDE.md establishes strict conventions (see
wiki/concepts/emil-design-eng.md in the vault for the design rationale).
"""
from __future__ import annotations

import re
from dataclasses import dataclass


_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n(.*)\Z", re.DOTALL)


@dataclass
class Wikilink:
    """One [[wiki-link]] occurrence in a note body."""

    target: str  # the file path or note name, e.g. "wiki/projects/parvis-ai" or "Ascent Studios Co/Website"
    label: str  # the display text (alias if present, else target)
    position: int  # character offset in the body where the [[ opens

    def lookup_key(self) -> str:
        """Return the canonical key for looking up this link in the wiki index.

        Strips a trailing .md (Obsidian treats 'foo' and 'foo.md' as the same note)
        and lowercases for case-insensitive matching.
        """
        key = self.target
        if key.endswith(".md"):
            key = key[:-3]
        return key.lower()


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """Return (frontmatter_dict, body_after_frontmatter).

    The body still contains the H1 and everything after the closing `---`.
    If there is no frontmatter, returns ({}, original_text).

    YAML parsing uses PyYAML. Date values (e.g. `last_updated: 2026-05-11`)
    are coerced to ISO-8601 strings so the rest of the codebase can treat
    every frontmatter value as a JSON-compatible primitive. This matches
    what the wiki's existing pages expect (`sources` is a list of strings,
    `last_updated` is a string, etc.).
    """
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return ({}, text)
    import yaml  # imported lazily so non-YAML paths don't pay the cost

    raw_yaml = m.group(1)
    body = m.group(2)
    try:
        data = yaml.safe_load(raw_yaml) or {}
        if not isinstance(data, dict):
            return ({}, text)
        return (_coerce_primitives(data), body)
    except yaml.YAMLError:
        # Malformed YAML — return empty frontmatter, keep the body intact.
        return ({}, text)


def _coerce_primitives(value):
    """Recursively convert datetime/date values to ISO strings.

    PyYAML auto-parses `2026-05-11` as `datetime.date`. The rest of the
    app treats frontmatter as JSON-compatible primitives (str, int, float,
    bool, list, dict), so dates get stringified here.
    """
    import datetime
    if isinstance(value, datetime.datetime):
        return value.date().isoformat()
    if isinstance(value, datetime.date):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _coerce_primitives(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_coerce_primitives(v) for v in value]
    return value


def strip_frontmatter(text: str) -> str:
    """Return text with the leading frontmatter block (if any) removed.

    Convenience wrapper around parse_frontmatter. Useful when you only care
    about the body, not the metadata.
    """
    _, body = parse_frontmatter(text)
    return body


# === Wikilink extraction ===

# Match [[target]] or [[target|label]] — greedy on target, lazy on label.
# We do NOT match [[#heading]] (anchor-only) or ![[image.png]] (embed).
_WIKILINK_RE = re.compile(r"\[\[([^\[\]|#]+?)(?:\|([^\[\]]+?))?\]\]")

# Fenced code blocks ```...``` (greedy across newlines).
_FENCED_CODE_RE = re.compile(r"```.*?```", re.DOTALL)

# Inline code `...` (no newlines inside).
_INLINE_CODE_RE = re.compile(r"`[^`\n]+`")

# Obsidian-style #tags — must be at start of a word boundary, allow letters/digits/underscore/hyphen.
# We require at least one non-digit char so "#1" isn't matched as a tag.
_TAG_RE = re.compile(r"(?:^|[\s(\[])#([a-zA-Z][a-zA-Z0-9_/-]*)")

# Obsidian callout: > [!note] Title (or [!note]+ for foldable). Strips the leading ">"
# before matching.
_CALLOUT_RE = re.compile(r"^>\s*\[!(\w+)\][+-]?\s*(.*)$", re.MULTILINE)


def extract_wikilinks(text: str) -> list[Wikilink]:
    """Find all [[wiki-link]] references in text.

    Skips links inside fenced code blocks (```...```) and inline code (`...`).
    This matches what a human reading the note would consider "real" links.

    Wikilink syntax:
      [[target]]            — target is both the path and the display label
      [[target|label]]      — target is the path, label is the display text
      [[target#heading]]    — anchor within a note (we ignore the heading for now)

    Embeds (prefixed with !) are NOT matched by the regex (we require [[ not ![[).
    """
    # Mask out code regions so the wikilink regex skips them.
    # Use a placeholder char that's not [ or ] so the regex doesn't match.
    masked = _FENCED_CODE_RE.sub(lambda m: " " * len(m.group(0)), text)
    masked = _INLINE_CODE_RE.sub(lambda m: " " * len(m.group(0)), masked)

    results: list[Wikilink] = []
    for m in _WIKILINK_RE.finditer(masked):
        target = m.group(1).strip()
        # Drop anchor fragments like "page#heading" — we don't track those yet.
        if "#" in target:
            target = target.split("#", 1)[0]
        if not target:
            continue
        label = (m.group(2) or target).strip()
        results.append(Wikilink(target=target, label=label, position=m.start()))
    return results


# === Tag extraction ===

def extract_tags(text: str) -> list[str]:
    """Return the list of Obsidian-style #tags found in `text`.

    Skips tags inside fenced code blocks and inline code (same mask approach
    as wikilinks). Returns lowercase, deduplicated tags in first-seen order.
    Tags may include slashes (for nested tags like #project/active) and
    hyphens.

    Tags inside Obsidian wikilinks like [[#heading]] are NOT extracted —
    those are anchors, not tags. (Our regex requires word boundary at start.)
    """
    masked = _FENCED_CODE_RE.sub(lambda m: " " * len(m.group(0)), text)
    masked = _INLINE_CODE_RE.sub(lambda m: " " * len(m.group(0)), masked)
    seen: set[str] = set()
    out: list[str] = []
    for m in _TAG_RE.finditer(masked):
        tag = m.group(1).lower().rstrip("/")
        if tag and tag not in seen:
            seen.add(tag)
            out.append(tag)
    return out


# === Callout extraction ===

def extract_callouts(text: str) -> list[dict]:
    """Return Obsidian callout blocks found in `text`.

    A callout is a blockquote starting with `[!type]` (or `[!type]+`/`[!type]-`).
    We don't try to capture the full multi-line body — just the type and
    first-line title. Useful for the dashboard to surface "Note", "Warning",
    "Tip", "Quote", "Example" blocks distinctly.
    """
    results: list[dict] = []
    for m in _CALLOUT_RE.finditer(text):
        results.append({
            "type": m.group(1).lower(),
            "title": m.group(2).strip() or None,
            "position": m.start(),
        })
    return results


def extract_metadata(text: str) -> dict:
    """One-shot metadata extraction: frontmatter + wikilinks + tags + callouts.

    Used by the page-content endpoint to return everything the dashboard
    needs to render a single Obsidian note without re-parsing.
    """
    fm, body = parse_frontmatter(text)
    wikilinks = extract_wikilinks(body)
    tags = extract_tags(body)
    callouts = extract_callouts(body)
    # Aliases: Obsidian stores them in frontmatter as `aliases: [Foo, Bar]`
    # or `alias: Foo`. Normalize to list[str].
    aliases_raw = fm.get("aliases") or fm.get("alias") or []
    if isinstance(aliases_raw, str):
        aliases = [aliases_raw]
    elif isinstance(aliases_raw, list):
        aliases = [a for a in aliases_raw if isinstance(a, str)]
    else:
        aliases = []
    # cssclass: Obsidian stores a single string or list. We don't currently
    # surface it in the dashboard but expose it for completeness.
    cssclass_raw = fm.get("cssclass") or fm.get("cssclasses") or []
    if isinstance(cssclass_raw, str):
        cssclass = [cssclass_raw]
    elif isinstance(cssclass_raw, list):
        cssclass = [c for c in cssclass_raw if isinstance(c, str)]
    else:
        cssclass = []
    return {
        "frontmatter": fm,
        "wikilinks": [{"target": wl.target, "label": wl.label, "position": wl.position} for wl in wikilinks],
        "tags": tags,
        "callouts": callouts,
        "aliases": aliases,
        "cssclass": cssclass,
    }
