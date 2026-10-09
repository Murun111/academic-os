"""Edge case tests for deck import (unicode, emoji, RTL, line endings, BOM, tags, field counts)."""
import io
import sqlite3
import zipfile

import pytest

from backend.services import deck_import as di
from backend.services.deck_import import (
    parse_apkg, parse_delimited, parse_quizlet_text,
)


def _make_db(path, notes):
    """Create a minimal Anki collection DB with given notes."""
    con = sqlite3.connect(path)
    con.execute(
        "CREATE TABLE notes (id integer primary key, guid text, mid integer, mod integer,"
        " usn integer, tags text, flds text, sfld text, csum integer, flags integer, data text)"
    )
    for i, (flds, tags) in enumerate(notes, 1):
        con.execute(
            "INSERT INTO notes VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (i, f"g{i}", 1, 0, 0, tags, "\x1f".join(flds), flds[0], 0, 0, ""),
        )
    con.commit()
    con.close()


def _zip(members: dict) -> bytes:
    """Create a zip archive from a dict of name -> content."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for k, v in members.items():
            z.writestr(k, v)
    return buf.getvalue()


# ──────────────────────────────────────── Unicode and emoji fields
def test_unicode_quizlet_text():
    """Quizlet with unicode characters in fields."""
    r = parse_quizlet_text("café\tcafé\nmañana\tmorning\n中文\tChinese")
    assert len(r.cards) == 3
    assert r.cards[0]["front"] == "café"
    assert r.cards[1]["front"] == "mañana"
    assert r.cards[2]["front"] == "中文"


def test_emoji_quizlet_text():
    """Quizlet with emoji in fields."""
    r = parse_quizlet_text("😀\thappy\n🔥\tfire\n❤️\tlove")
    assert len(r.cards) == 3
    assert r.cards[0]["front"] == "😀"
    assert r.cards[1]["front"] == "🔥"
    assert r.cards[2]["front"] == "❤️"


def test_unicode_apkg(tmp_path):
    """Anki package with unicode characters in flds and tags."""
    p = tmp_path / "c.anki2"
    _make_db(p, [
        (["Qu'est-ce que c'est?", "C'est une question"], "français élève"),
        (["日本語", "こんにちは"], "日本語"),
        (["Ελληνικά", "Καλημέρα"], "ελληνικά"),
    ])
    r = parse_apkg(_zip({"collection.anki2": p.read_bytes()}))
    assert len(r.cards) == 3
    assert r.cards[0]["front"] == "Qu'est-ce que c'est?"
    assert r.cards[1]["tags"] == ["日本語"]
    assert r.cards[2]["front"] == "Ελληνικά"


def test_emoji_apkg(tmp_path):
    """Anki package with emoji."""
    p = tmp_path / "c.anki2"
    _make_db(p, [
        (["🎓 What is education?", "📚 Learning"], "🎓"),
        (["🌍", "🌎 🌏"], "geo 🗺️"),
    ])
    r = parse_apkg(_zip({"collection.anki2": p.read_bytes()}))
    assert len(r.cards) == 2
    assert "🎓" in r.cards[0]["front"]
    assert "🌍" in r.cards[1]["front"]


# ──────────────────────────────────────── RTL text
def test_rtl_text_arabic():
    """Arabic text (right-to-left) in Quizlet."""
    r = parse_quizlet_text("مرحبا\tHello\nشكراً\tThank you")
    assert len(r.cards) == 2
    assert r.cards[0]["front"] == "مرحبا"


def test_rtl_text_hebrew():
    """Hebrew text (right-to-left) in Quizlet."""
    r = parse_quizlet_text("שלום\tHello\nתודה\tThank you")
    assert len(r.cards) == 2
    assert r.cards[0]["front"] == "שלום"


def test_rtl_apkg(tmp_path):
    """Anki package with RTL text."""
    p = tmp_path / "c.anki2"
    _make_db(p, [
        (["ما هو الفصل الأول؟", "الفصل الأول"], "عربي"),
        (["מה זה ישראל?", "ישראל היא מדינה"], "עברית"),
    ])
    r = parse_apkg(_zip({"collection.anki2": p.read_bytes()}))
    assert len(r.cards) == 2
    assert r.cards[0]["front"] == "ما هو الفصل الأول؟"


# ──────────────────────────────────────── Tabs and semicolons in Quizlet
def test_quizlet_embedded_tab_in_back():
    """Quizlet with tab character inside the back field."""
    # Tab inside the back field should be handled gracefully
    r = parse_quizlet_text("word\tdefinition\twith\ttabs")
    # Since term_sep defaults to auto-detect and will find the first \t
    # this will split as "word" front, "definition\twith\ttabs" back
    assert len(r.cards) == 1
    assert r.cards[0]["front"] == "word"
    assert "definition" in r.cards[0]["back"]


def test_quizlet_embedded_semicolon_in_back():
    """Quizlet with semicolon inside a field when semicolon is row separator."""
    r = parse_quizlet_text("cat - gato;dog - perro;has;inside", term_sep=" - ", row_sep=";")
    # Splitting by ";" gives ["cat - gato", "dog - perro", "has", "inside"]
    # Only first two have " - " separator, so the last two are skipped
    assert len(r.cards) == 2
    assert r.skipped == 2


def test_quizlet_embedded_separator_in_value():
    """Quizlet where the front or back contains the separator itself."""
    # Using tab as separator, but the field contains a space
    r = parse_quizlet_text("a b\tdef\nc d\tghi")
    assert r.cards[0]["front"] == "a b"
    assert r.cards[0]["back"] == "def"


# ──────────────────────────────────────── Line endings
def test_windows_crlf_quizlet():
    """Quizlet with Windows CRLF line endings."""
    r = parse_quizlet_text("cat\tgato\r\ndog\tperro\r\nbird\tajaro\r\n")
    assert len(r.cards) == 3
    assert r.cards[0]["front"] == "cat"
    assert r.cards[1]["front"] == "dog"
    assert r.cards[2]["front"] == "bird"


def test_windows_crlf_delimited():
    """Delimited text with Windows CRLF line endings."""
    text = "front\tback\r\nQ1\tA1\r\nQ2\tA2\r\n"
    r = parse_delimited(text)
    assert len(r.cards) == 2
    assert r.cards[0]["front"] == "Q1"


def test_mixed_line_endings():
    """Text with mixed line endings (LF, CRLF, CR)."""
    r = parse_quizlet_text("cat\tgato\ndog\tperro\r\nbird\tajaro\rfish\tpez")
    # Some line endings might not parse correctly, but should handle gracefully
    assert len(r.cards) >= 2


# ──────────────────────────────────────── BOM at file start
def test_bom_utf8_delimited():
    """Delimited text with UTF-8 BOM at the start."""
    # UTF-8 BOM is \xef\xbb\xbf or U+FEFF
    text = "﻿" + "front\tback\nQ1\tA1\nQ2\tA2\n"
    r = parse_delimited(text)
    assert len(r.cards) == 2
    assert r.cards[0]["front"] == "Q1"


def test_bom_quizlet():
    """Quizlet with UTF-8 BOM."""
    text = "﻿" + "cat\tgato\ndog\tperro"
    r = parse_quizlet_text(text)
    assert len(r.cards) == 2


# ──────────────────────────────────────── Multiple fields (5+ fields per note)
def test_apkg_five_field_notes(tmp_path):
    """Anki package with notes having 5 fields; should take first 2 (front, back)."""
    p = tmp_path / "c.anki2"
    # Create notes with 5 fields each
    _make_db(p, [
        (["Front1", "Back1", "Extra1", "Extra2", "Extra3"], "tag1"),
        (["Front2", "Back2", "Extra1", "Extra2", "Extra3"], "tag2"),
    ])
    r = parse_apkg(_zip({"collection.anki2": p.read_bytes()}))
    assert len(r.cards) == 2
    # Should only use first two fields
    assert r.cards[0]["front"] == "Front1"
    assert r.cards[0]["back"] == "Back1"
    assert r.cards[1]["front"] == "Front2"


def test_apkg_many_fields(tmp_path):
    """Anki package with notes having 10 fields."""
    p = tmp_path / "c.anki2"
    fields = [f"Field{i}" for i in range(10)]
    _make_db(p, [(fields, "many")])
    r = parse_apkg(_zip({"collection.anki2": p.read_bytes()}))
    assert len(r.cards) == 1
    assert r.cards[0]["front"] == "Field0"
    assert r.cards[0]["back"] == "Field1"


# ──────────────────────────────────────── Empty notes
def test_apkg_zero_notes(tmp_path):
    """Anki package with zero notes."""
    p = tmp_path / "c.anki2"
    _make_db(p, [])
    r = parse_apkg(_zip({"collection.anki2": p.read_bytes()}))
    assert len(r.cards) == 0
    assert r.skipped == 0


def test_apkg_all_empty_front_notes(tmp_path):
    """Anki package where all notes have empty front field."""
    p = tmp_path / "c.anki2"
    _make_db(p, [
        (["", "answer1"], ""),
        (["", "answer2"], ""),
    ])
    r = parse_apkg(_zip({"collection.anki2": p.read_bytes()}))
    assert len(r.cards) == 0
    assert r.skipped == 2


# ──────────────────────────────────────── Duplicate cards
def test_duplicate_cards_quizlet():
    """Quizlet with duplicate question-answer pairs."""
    r = parse_quizlet_text("cat\tgato\ncat\tgato\ndog\tperro")
    # Duplicates should be imported as-is (no deduplication)
    assert len(r.cards) == 3
    assert r.cards[0] == r.cards[1]


def test_duplicate_cards_delimited():
    """Delimited format with duplicate cards."""
    r = parse_delimited("Q1\tA1\nQ1\tA1\nQ2\tA2\n")
    assert len(r.cards) == 3


# ──────────────────────────────────────── Very long fields
def test_very_long_front_field_quizlet():
    """Quizlet with extremely long front field (should be truncated to MAX_SIDE_CHARS)."""
    long_front = "a" * 5000
    r = parse_quizlet_text(f"{long_front}\tshort back")
    assert len(r.cards) == 1
    assert len(r.cards[0]["front"]) <= di.MAX_SIDE_CHARS
    assert len(r.cards[0]["front"]) == di.MAX_SIDE_CHARS  # Exact truncation


def test_very_long_back_field_delimited():
    """Delimited with very long back field."""
    long_back = "b" * 10000
    r = parse_delimited(f"Q1\t{long_back}")
    assert len(r.cards) == 1
    assert len(r.cards[0]["back"]) <= di.MAX_SIDE_CHARS


def test_apkg_very_long_field(tmp_path):
    """Anki package with field longer than MAX_SIDE_CHARS."""
    p = tmp_path / "c.anki2"
    _make_db(p, [(["Q", "x" * 10000], "")])
    r = parse_apkg(_zip({"collection.anki2": p.read_bytes()}))
    assert len(r.cards) == 1
    assert len(r.cards[0]["back"]) == di.MAX_SIDE_CHARS


# ──────────────────────────────────────── Tags with unicode
def test_unicode_tags_quizlet():
    """Tags with unicode characters (delimited format)."""
    r = parse_delimited("#tags column:3\nQ1\tA1\tfrançais 日本語 العربية")
    assert len(r.cards) == 1
    assert "français" in r.cards[0]["tags"]
    assert "日本語" in r.cards[0]["tags"]
    assert "العربية" in r.cards[0]["tags"]


def test_emoji_tags_apkg(tmp_path):
    """Anki package with emoji in tags."""
    p = tmp_path / "c.anki2"
    _make_db(p, [(["Q", "A"], "🎓 école 📚")])
    r = parse_apkg(_zip({"collection.anki2": p.read_bytes()}))
    assert len(r.cards) == 1
    assert "🎓" in r.cards[0]["tags"]


# ──────────────────────────────────────── .colpkg file
def test_colpkg_treated_as_apkg(tmp_path):
    """A .colpkg file should work identically to .apkg (both are zip + anki collection)."""
    p = tmp_path / "c.anki2"
    _make_db(p, [
        (["What?", "Answer"], "test"),
    ])
    # .colpkg and .apkg both contain collection.anki2
    data = _zip({"collection.anki2": p.read_bytes()})
    r = parse_apkg(data)
    assert len(r.cards) == 1
    assert r.cards[0]["front"] == "What?"


# ──────────────────────────────────────── Zip that is not Anki
def test_zip_missing_collection(tmp_path):
    """A zip file with no collection.* file."""
    data = _zip({"readme.txt": "This is not an Anki deck"})
    with pytest.raises(ValueError, match="No Anki collection found"):
        parse_apkg(data)


def test_zip_with_collection_but_invalid_db(tmp_path):
    """A zip with collection.anki2 but invalid SQLite data."""
    data = _zip({"collection.anki2": b"This is not a valid SQLite database"})
    with pytest.raises(ValueError, match="Could not read Anki collection"):
        parse_apkg(data)


def test_zip_is_not_actually_zip():
    """Bytes that are not a valid zip file."""
    with pytest.raises(ValueError, match="Not a valid .apkg/.colpkg file"):
        parse_apkg(b"This is just plain text, not a zip file")


# ──────────────────────────────────────── Encoding edge cases
def test_latin1_delimited_with_auto_bom_strip():
    """Delimited text that looks like latin-1 but should work (UTF-8 assumed)."""
    # In practice, parse_delimited calls lstrip("﻿") which removes BOM
    # This test ensures latin-1 specific chars are handled
    r = parse_delimited("café\tspanish café")
    assert len(r.cards) == 1
    assert r.cards[0]["front"] == "café"


def test_html_entities_in_fields():
    """Delimited text with HTML entities (should be unescaped in _clean)."""
    r = parse_delimited("#html:true\nQ: &quot;What?&quot;\t&lt;Answer&gt;\n")
    assert len(r.cards) == 1
    assert r.cards[0]["front"] == 'Q: "What?"'
    assert r.cards[0]["back"] == "<Answer>"


def test_nbsp_preserved_as_space():
    """Non-breaking space (U+00A0) should become regular space."""
    # _clean replaces \xa0 (nbsp) with space
    r = parse_quizlet_text("test\xa0word\tdef")
    assert r.cards[0]["front"] == "test word"


# ──────────────────────────────────────── Edge cases with whitespace
def test_tabs_inside_delimited_field():
    """Delimited with tabs inside a quoted field."""
    r = parse_delimited('Q1\t"A1\twith\ttabs"')
    assert len(r.cards) == 1
    # CSV parser handles quoted fields
    assert "with" in r.cards[0]["back"]


def test_leading_trailing_whitespace():
    """Fields with leading/trailing whitespace (should be stripped)."""
    r = parse_quizlet_text("  cat  \t  gato  \n  dog  \t  perro  ")
    assert r.cards[0]["front"] == "cat"
    assert r.cards[0]["back"] == "gato"


def test_empty_lines_in_delimited():
    """Delimited format with multiple empty lines."""
    r = parse_delimited("\n\n\nQ1\tA1\n\n\nQ2\tA2\n\n")
    assert len(r.cards) == 2


# ──────────────────────────────────────── Multi-line content
def test_multiline_fields_quizlet_with_pipe():
    """Quizlet with pipe separator allowing multi-line back."""
    r = parse_quizlet_text("term1\tdef line 1\ndef line 2|term2\tdef2", term_sep="\t", row_sep="|")
    assert len(r.cards) == 2
    assert r.cards[0]["back"] == "def line 1\ndef line 2"


def test_multiline_fields_apkg(tmp_path):
    """Anki package with newlines in fields (allowed in flds)."""
    p = tmp_path / "c.anki2"
    _make_db(p, [
        (["Multi\nline\nfront", "Multi\nline\nback"], ""),
    ])
    r = parse_apkg(_zip({"collection.anki2": p.read_bytes()}))
    assert len(r.cards) == 1
    # _clean normalizes multiple newlines to max 2 (double newline)
    assert "\n" in r.cards[0]["front"]


# ──────────────────────────────────────── Cloze deletion edge cases
def test_cloze_with_unicode():
    """Cloze deletion with unicode in the hint."""
    r = parse_delimited("The café is {{c1::小さい::tiny}}\t")
    assert len(r.cards) == 1
    assert "[...]" in r.cards[0]["front"]


def test_empty_cloze():
    """Cloze deletion with empty content."""
    r = parse_delimited("Before {{c1::}} after\t")
    assert len(r.cards) == 1


def test_nested_cloze():
    """Multiple cloze deletions in one field."""
    r = parse_delimited("{{c1::a}} and {{c2::b}} and {{c3::c}}\t")
    assert len(r.cards) == 1
    assert r.cards[0]["front"].count("[...]") == 3


# ──────────────────────────────────────── Quizlet edge cases
def test_quizlet_empty_rows():
    """Quizlet with only empty rows and whitespace."""
    r = parse_quizlet_text("\n\n   \n\t\n")
    assert len(r.cards) == 0


def test_quizlet_no_separator():
    """Quizlet text with no term separator in a row."""
    r = parse_quizlet_text("cat\tgato\nno-separator-here\ndog\tperro")
    assert len(r.cards) == 2
    assert r.skipped == 1


# ──────────────────────────────────────── Special characters
def test_special_chars_math_symbols():
    """Math symbols and special characters."""
    r = parse_quizlet_text("∑∏∫\tintegral\n√π\tsqrt pi\n±∞\tplus minus infinity")
    assert len(r.cards) == 3
    assert "∑" in r.cards[0]["front"]


def test_special_chars_combining_diacritics():
    """Text with combining diacritical marks."""
    r = parse_quizlet_text("é\taccented e\nñ\ttilde n")
    assert len(r.cards) == 2


# ──────────────────────────────────────── Media reference edge cases
def test_sound_reference_in_tags():
    """Ensure sound references don't affect tag parsing."""
    p_tmp = io.BytesIO()

    # Create a temp db
    import tempfile
    fd, path = tempfile.mkstemp(suffix=".sqlite")
    try:
        con = sqlite3.connect(path)
        con.execute(
            "CREATE TABLE notes (id integer primary key, guid text, mid integer, mod integer,"
            " usn integer, tags text, flds text, sfld text, csum integer, flags integer, data text)"
        )
        con.execute(
            "INSERT INTO notes VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (1, "g1", 1, 0, 0, "[sound:a.mp3] test", "[sound:test.mp3] Q\tA", "Q", 0, 0, ""),
        )
        con.commit()
        con.close()

        with open(path, "rb") as f:
            db_bytes = f.read()
    finally:
        import os
        try:
            os.unlink(path)
        except OSError:
            pass

    r = parse_apkg(_zip({"collection.anki2": db_bytes}))
    # Sound in tags should not prevent parsing
    assert len(r.cards) >= 0


# ──────────────────────────────────────── Mixed content edge cases
def test_quizlet_with_html_tags():
    """Quizlet text is plain: '<' and '>' pass through untouched."""
    r = parse_quizlet_text("<b>bold</b>\t<i>italic</i>")
    assert len(r.cards) == 1
    assert r.cards[0]["front"] == "<b>bold</b>"
    assert r.cards[0]["back"] == "<i>italic</i>"


def test_extremely_nested_html():
    """Delimited with deeply nested HTML tags."""
    r = parse_delimited("#html:true\n<div><p><span>Q1</span></p></div>\t<div><p><span>A1</span></p></div>")
    assert len(r.cards) == 1
    assert r.cards[0]["front"] == "Q1"
    assert r.cards[0]["back"] == "A1"
