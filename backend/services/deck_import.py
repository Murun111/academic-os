"""Flashcard deck import parsing (Quizlet text, Anki text/CSV, .apkg/.colpkg).

Pure parsing: takes text or bytes, returns an ImportResult. No network, and no
file I/O beyond a temp file needed to open SQLite from bytes.
"""
from __future__ import annotations

import csv
import io
import os
import re
import sqlite3
import tempfile
import zipfile
from dataclasses import dataclass, field
from html import unescape

MAX_ZIP_BYTES = 100 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 300 * 1024 * 1024
MAX_CARDS = 20_000
MAX_SIDE_CHARS = 2000

_MEDIA_MSG = "{n} cards referenced images or audio, which were not imported"

_SOUND_RE = re.compile(r"\[sound:[^\]]*\]", re.IGNORECASE)
_IMG_RE = re.compile(r"<img\b[^>]*>", re.IGNORECASE)
_BR_RE = re.compile(r"<br\s*/?>", re.IGNORECASE)
_BLOCK_CLOSE_RE = re.compile(r"</(?:div|p|li|tr)\s*>", re.IGNORECASE)
_BLOCK_OPEN_RE = re.compile(r"<(?:div|p)\b[^>]*>", re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]*>")
_CLOZE_RE = re.compile(r"\{\{c\d+::(.*?)(?:::(.*?))?\}\}", re.DOTALL)


@dataclass
class ImportResult:
    cards: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    skipped: int = 0


class _Builder:
    """Accumulates cards, tracking media references and the card cap."""

    def __init__(self) -> None:
        self.result = ImportResult()
        self.media_cards = 0
        self.truncated = False

    def add(
        self, front: str, back: str, tags: list[str] | None = None, html: bool = False,
    ) -> None:
        if len(self.result.cards) >= MAX_CARDS:
            self.truncated = True
            return
        has_media = bool(_SOUND_RE.search(front) or _SOUND_RE.search(back))
        if html:
            has_media = has_media or bool(_IMG_RE.search(front) or _IMG_RE.search(back))
        f, b = _clean(front, html), _clean(back, html)
        if not f:
            self.result.skipped += 1
            return
        if has_media:
            self.media_cards += 1
        self.result.cards.append({"front": f, "back": b, "tags": list(tags or [])})

    def finish(self) -> ImportResult:
        if self.media_cards:
            self.result.warnings.append(_MEDIA_MSG.format(n=self.media_cards))
        if self.truncated:
            self.result.warnings.append(
                f"Deck has more than {MAX_CARDS} cards; only the first {MAX_CARDS} were imported"
            )
        return self.result


def _clean(s: str, html: bool = False) -> str:
    """Normalise one card side. Tags and entities are touched only when html is
    True; plain text keeps '<', '>' and '&amp;' literally."""
    s = _SOUND_RE.sub("", s)
    if html:
        s = _IMG_RE.sub("", s)
        s = _BR_RE.sub("\n", s)
        s = _BLOCK_CLOSE_RE.sub("\n", s)
        s = _BLOCK_OPEN_RE.sub("\n", s)
        s = _TAG_RE.sub("", s)
        s = unescape(s)
    s = s.replace("\xa0", " ").replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[ \t\f\v]+", " ", ln).strip() for ln in s.split("\n")]
    s = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    return s[:MAX_SIDE_CHARS]


def _split_cloze(text: str) -> tuple[str, str] | None:
    if not _CLOZE_RE.search(text):
        return None
    front = _CLOZE_RE.sub("[...]", text)
    back = _CLOZE_RE.sub(lambda m: m.group(1), text)
    return front, back


# ---------------------------------------------------------------- Quizlet

def parse_quizlet_text(text: str, term_sep: str = "\t", row_sep: str = "\n") -> ImportResult:
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n").strip("\n")
    b = _Builder()
    if not text.strip():
        return b.finish()

    if row_sep == "auto":
        row_sep = "\n" if "\n" in text.strip() else ";"
    if term_sep == "auto":
        if "\t" in text:
            term_sep = "\t"
        else:
            # majority of rows decides, so one stray " - " in comma data is harmless
            rows = [r for r in text.split(row_sep) if r.strip()]
            dash = sum(" - " in r for r in rows)
            comma = sum("," in r for r in rows)
            term_sep = " - " if dash and dash >= comma else ","
    if not term_sep or not row_sep:
        raise ValueError("separators must be non-empty")

    for row in text.split(row_sep):
        if not row.strip():
            continue
        if term_sep not in row:
            b.result.skipped += 1
            continue
        front, back = row.split(term_sep, 1)
        b.add(front, back)
    return b.finish()


# ------------------------------------------------------- Anki text / CSV

_SEP_NAMES = {"tab": "\t", "comma": ",", "semicolon": ";", "space": " ", "pipe": "|", "colon": ":"}


_HEADER_RE = re.compile(r"#(\w[\w ]*?):(.*)$")


def parse_delimited(text: str) -> ImportResult:
    text = (text or "").lstrip("﻿").replace("\r\n", "\n").replace("\r", "\n")
    b = _Builder()
    delimiter = "\t"
    explicit_sep = False
    tags_col: int | None = None
    drop_cols: set[int] = set()
    html = False
    lines = text.split("\n")
    start = 0
    # Anki rule: '#key:value' headers are read only until the first other line.
    while start < len(lines):
        m = _HEADER_RE.match(lines[start].strip()) if lines[start].startswith("#") else None
        if not m:
            break
        key, val = m.group(1).strip().lower(), m.group(2).strip()
        if key == "separator":
            delimiter = _SEP_NAMES.get(val.lower(), val[:1] or "\t")
            explicit_sep = True
        elif key == "html":
            html = val.lower() == "true"
        elif key == "tags column" and val.isdigit():
            tags_col = int(val) - 1
        elif key in ("guid column", "notetype column", "deck column") and val.isdigit():
            drop_cols.add(int(val) - 1)
        start += 1
    body = lines[start:]

    first = next((ln for ln in body if ln.strip()), "")
    header_cells = [c.strip().lower() for c in re.split(r"[,\t;]", first)]
    has_header = header_cells[:2] == ["front", "back"]
    if has_header and not explicit_sep:
        delimiter = "\t" if "\t" in first else ("," if "," in first else ";")

    rows = csv.reader(io.StringIO("\n".join(body)), delimiter=delimiter)
    header_skipped = False
    try:
        for row in rows:
            if not row or all(not c.strip() for c in row):
                continue
            if has_header and not header_skipped:
                header_skipped = True
                continue
            tags: list[str] = []
            if tags_col is not None and tags_col < len(row):
                tags = row[tags_col].split()
            cols = [c for i, c in enumerate(row) if i not in drop_cols and i != tags_col]
            if len(cols) < 2:
                b.result.skipped += 1
                continue
            front, back = cols[0], cols[1]
            cz = _split_cloze(front)
            if cz:
                front, back = cz
            b.add(front, back, tags, html=html)
    except csv.Error as e:
        raise ValueError(f"Could not parse delimited text: {e}") from e
    return b.finish()


# ------------------------------------------------------------------- apkg

def _read_member(zf: zipfile.ZipFile, name: str) -> bytes:
    with zf.open(name) as fh:
        data = fh.read(MAX_UNCOMPRESSED_BYTES + 1)
    if len(data) > MAX_UNCOMPRESSED_BYTES:
        raise ValueError("Archive entry is too large")
    return data


def _zstd_decompress(data: bytes) -> bytes:
    try:
        from compression import zstd  # stdlib from Python 3.14
    except ImportError as e:
        raise ValueError(
            "This deck uses Anki's newer compressed format, which this build can't read. "
            "In Anki, export again with \"Support older Anki versions\" checked."
        ) from e

    try:
        d = zstd.ZstdDecompressor()
        out = d.decompress(data, MAX_UNCOMPRESSED_BYTES + 1)
    except Exception as e:  # zstd.ZstdError and friends
        raise ValueError(f"Could not decompress collection: {e}") from e
    if len(out) > MAX_UNCOMPRESSED_BYTES or not d.eof:
        raise ValueError("Archive entry is too large")
    return out


def parse_apkg(data: bytes) -> ImportResult:
    if len(data) > MAX_ZIP_BYTES:
        raise ValueError("File is larger than 100 MB")
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as e:
        raise ValueError("Not a valid .apkg/.colpkg file") from e
    with zf:
        infos = zf.infolist()
        if sum(i.file_size for i in infos) > MAX_UNCOMPRESSED_BYTES or any(
            i.file_size > MAX_UNCOMPRESSED_BYTES for i in infos
        ):
            raise ValueError("Archive expands to more than 300 MB")
        names = {i.filename for i in infos}
        try:
            if "collection.anki21b" in names:
                db_bytes = _zstd_decompress(_read_member(zf, "collection.anki21b"))
            elif "collection.anki21" in names:
                db_bytes = _read_member(zf, "collection.anki21")
            elif "collection.anki2" in names:
                db_bytes = _read_member(zf, "collection.anki2")
            else:
                raise ValueError("No Anki collection found in archive")
        except (zipfile.BadZipFile, RuntimeError, NotImplementedError, EOFError) as e:
            raise ValueError(f"Could not read archive: {e}") from e
    return _read_collection(db_bytes)


def _read_collection(db_bytes: bytes) -> ImportResult:
    b = _Builder()
    fd, path = tempfile.mkstemp(suffix=".sqlite")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(db_bytes)
        try:
            con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
            try:
                rows = con.execute("SELECT flds, tags FROM notes ORDER BY id").fetchall()
            finally:
                con.close()
        except sqlite3.DatabaseError as e:
            raise ValueError(f"Could not read Anki collection: {e}") from e
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass

    for flds, tags in rows:
        parts = (flds or "").split("\x1f")
        front = parts[0]
        back = parts[1] if len(parts) > 1 else ""
        cz = _split_cloze(front)
        if cz:
            front, back = cz
        b.add(front, back, (tags or "").split(), html=True)
    return b.finish()


def looks_like_header(text: str) -> bool:
    """True when text starts with an Anki '#key:value' header line."""
    first = (text or "").lstrip("\ufeff").lstrip().split("\n", 1)[0].strip()
    return bool(_HEADER_RE.match(first)) if first.startswith("#") else False
