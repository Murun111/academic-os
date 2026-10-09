import io
import sqlite3
import zipfile
from compression import zstd

import pytest

from backend.services import deck_import as di
from backend.services.deck_import import (
    parse_apkg, parse_delimited, parse_quizlet_text,
)


def _make_db(path, notes):
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
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for k, v in members.items():
            z.writestr(k, v)
    return buf.getvalue()


NOTES = [
    (["What is 2+2?", "4"], " math easy "),
    (["Only front"], ""),
    ([""], ""),
    (["<div>Cap&amp;ital</div><br>of <b>France</b>?", "Paris&nbsp;city"], "geo"),
]


def test_apkg_anki2(tmp_path):
    p = tmp_path / "c.anki2"
    _make_db(p, NOTES)
    r = parse_apkg(_zip({"collection.anki2": p.read_bytes()}))
    assert [c["front"] for c in r.cards] == ["What is 2+2?", "Only front", "Cap&ital\n\nof France?"]
    assert r.cards[0] == {"front": "What is 2+2?", "back": "4", "tags": ["math", "easy"]}
    assert r.cards[1]["back"] == ""
    assert r.cards[2]["back"] == "Paris city"
    assert r.skipped == 1


def test_apkg_zstd_preferred(tmp_path):
    p = tmp_path / "c.db"
    _make_db(p, [(["new", "format"], "")])
    q = tmp_path / "old.db"
    _make_db(q, [(["old", "format"], "")])
    data = _zip({
        "collection.anki21b": zstd.compress(p.read_bytes()),
        "collection.anki2": q.read_bytes(),
    })
    r = parse_apkg(data)
    assert [c["front"] for c in r.cards] == ["new"]


def test_apkg_anki21_over_anki2(tmp_path):
    p = tmp_path / "a.db"
    _make_db(p, [(["v21", "x"], "")])
    q = tmp_path / "b.db"
    _make_db(q, [(["v2", "x"], "")])
    r = parse_apkg(_zip({"collection.anki21": p.read_bytes(), "collection.anki2": q.read_bytes()}))
    assert r.cards[0]["front"] == "v21"


def test_media_and_cloze(tmp_path):
    p = tmp_path / "c.db"
    _make_db(p, [
        (['Look <img src="a.png"> here', "x [sound:a.mp3]"], ""),
        (["The {{c1::heart}} pumps {{c2::blood::fluid}}", "extra"], "bio"),
    ])
    r = parse_apkg(_zip({"collection.anki2": p.read_bytes()}))
    assert r.cards[0]["front"] == "Look here"
    assert r.cards[0]["back"] == "x"
    assert r.cards[1]["front"] == "The [...] pumps [...]"
    assert r.cards[1]["back"] == "The heart pumps blood"
    assert r.warnings == ["1 cards referenced images or audio, which were not imported"]


def test_cap_side_length(tmp_path):
    p = tmp_path / "c.db"
    _make_db(p, [(["q", "a" * 5000], "")])
    r = parse_apkg(_zip({"collection.anki2": p.read_bytes()}))
    assert len(r.cards[0]["back"]) == 2000


def test_card_limit(monkeypatch):
    monkeypatch.setattr(di, "MAX_CARDS", 3)
    r = parse_quizlet_text("\n".join(f"a{i}\tb{i}" for i in range(5)))
    assert len(r.cards) == 3
    assert any("only the first 3" in w for w in r.warnings)


def test_malformed_and_limits(monkeypatch):
    with pytest.raises(ValueError):
        parse_apkg(b"not a zip")
    with pytest.raises(ValueError):
        parse_apkg(_zip({"readme.txt": "x"}))
    with pytest.raises(ValueError):
        parse_apkg(_zip({"collection.anki2": b"garbage not sqlite" * 10}))
    monkeypatch.setattr(di, "MAX_ZIP_BYTES", 10)
    with pytest.raises(ValueError):
        parse_apkg(_zip({"collection.anki2": b"x" * 100}))


def test_zip_bomb(monkeypatch):
    monkeypatch.setattr(di, "MAX_UNCOMPRESSED_BYTES", 1000)
    with pytest.raises(ValueError):
        parse_apkg(_zip({"collection.anki2": b"\0" * 5000}))


def test_zstd_bomb(monkeypatch, tmp_path):
    big = zstd.compress(b"\0" * 5000)
    monkeypatch.setattr(di, "MAX_UNCOMPRESSED_BYTES", 1000)
    with pytest.raises(ValueError):
        parse_apkg(_zip({"collection.anki21b": big}))


def test_quizlet_tab():
    r = parse_quizlet_text("cat\tgato\ndog\tperro\n\nbad row\n")
    assert [(c["front"], c["back"]) for c in r.cards] == [("cat", "gato"), ("dog", "perro")]
    assert r.skipped == 1


def test_quizlet_dash_and_semicolon():
    r = parse_quizlet_text("cat - gato;dog - perro", term_sep=" - ", row_sep=";")
    assert len(r.cards) == 2 and r.cards[1]["back"] == "perro"
    r = parse_quizlet_text("cat - gato;dog - perro", term_sep="auto", row_sep="auto")
    assert [c["front"] for c in r.cards] == ["cat", "dog"]


def test_quizlet_auto_comma_and_multiline_def():
    r = parse_quizlet_text("a,b\nc,d, e", term_sep="auto")
    assert r.cards[1]["back"] == "d, e"
    r = parse_quizlet_text("t1\tline1\nline2|t2\tx", term_sep="\t", row_sep="|")
    assert r.cards[0]["back"] == "line1\nline2"


def test_anki_txt_headers():
    txt = "#separator:tab\n#html:true\n#tags column:3\nQ1<br>x\tA1\tt1 t2\nQ2\tA2\t\n"
    r = parse_delimited(txt)
    assert r.cards[0] == {"front": "Q1\nx", "back": "A1", "tags": ["t1", "t2"]}
    assert r.cards[1]["tags"] == []


def test_anki_txt_cloze():
    r = parse_delimited("#html:true\nThe {{c1::sun}} is hot\t\n")
    assert r.cards[0]["front"] == "The [...] is hot"
    assert r.cards[0]["back"] == "The sun is hot"


def test_csv_header():
    r = parse_delimited('front,back\n"a, b",c\nd,e\n')
    assert [(c["front"], c["back"]) for c in r.cards] == [("a, b", "c"), ("d", "e")]


def test_empty():
    assert parse_delimited("").cards == []
    assert parse_quizlet_text("").cards == []


# ---- review fixes
def test_plain_text_keeps_angle_brackets_and_entities():
    from backend.services.deck_import import parse_quizlet_text
    r = parse_quizlet_text("x < 5 and y > 3\tok\nList<String>\tgeneric\n&amp;\tamp")
    assert [c["front"] for c in r.cards] == ["x < 5 and y > 3", "List<String>", "&amp;"]


def test_delimited_html_header_strips_tags():
    from backend.services.deck_import import parse_delimited
    r = parse_delimited("#html:true\n<b>Q</b>\tA &amp; B")
    assert r.cards[0]["front"] == "Q" and r.cards[0]["back"] == "A & B"
    r = parse_delimited("#html:false\nList<String>\tA &amp; B")
    assert r.cards[0]["front"] == "List<String>" and r.cards[0]["back"] == "A &amp; B"


def test_hash_lines_after_header_block_are_data():
    from backend.services.deck_import import parse_delimited
    r = parse_delimited("#include <stdio.h>\tC header")
    assert r.cards[0]["front"] == "#include <stdio.h>"
    r = parse_delimited('#separator:tab\n"multi\n#line"\tback')
    assert r.cards[0]["front"] == "multi\n#line"


def test_auto_separator_majority_and_hash_quizlet():
    from backend.services.deck_import import parse_quizlet_text
    r = parse_quizlet_text("a,b\nc,d\ne - f,g\nh,i", "auto", "auto")
    assert len(r.cards) == 4 and r.skipped == 0
    r = parse_quizlet_text("#1\tanswer")
    assert r.cards[0]["front"] == "#1"
