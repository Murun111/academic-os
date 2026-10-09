import io
import sqlite3
import zipfile

import pytest
from fastapi.testclient import TestClient

from backend.app import app
from backend.routers import learning as learning_router
from backend.routers.learning import reset_service


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr("backend.vault.agentic_os_dir", lambda: tmp_path)
    reset_service()
    with TestClient(app) as c:
        yield c
    reset_service()


def _apkg(notes) -> bytes:
    path = io.BytesIO()
    import tempfile, os
    fd, p = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    con = sqlite3.connect(p)
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
    with zipfile.ZipFile(path, "w") as z:
        z.write(p, "collection.anki2")
    os.unlink(p)
    return path.getvalue()


APKG_NOTES = [(["Q1", "A1"], " bio "), (["Q2", "A2"], "")]


def _deck_count(client):
    return len(client.get("/api/learning/decks").json())


def test_preview_apkg(client):
    r = client.post(
        "/api/learning/import/preview",
        files={"file": ("x.apkg", _apkg(APKG_NOTES), "application/octet-stream")},
    )
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["total"] == 2
    assert j["cards"][0] == {"front": "Q1", "back": "A1", "tags": ["bio"]}
    assert _deck_count(client) == 0


def test_preview_caps_at_20_and_saves_nothing(client):
    text = "\n".join(f"t{i}\td{i}" for i in range(30))
    r = client.post("/api/learning/import/preview", data={"text": text})
    assert r.status_code == 200
    j = r.json()
    assert j["total"] == 30 and len(j["cards"]) == 20
    assert _deck_count(client) == 0


def test_import_apkg_detected_by_magic(client):
    r = client.post(
        "/api/learning/import",
        data={"deck_title": "Bio", "course_id": "c1", "course_name": "Biology"},
        files={"file": ("noext", _apkg(APKG_NOTES), "application/octet-stream")},
    )
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["imported"] == 2
    assert j["deck"]["title"] == "Bio"
    assert j["deck"]["course_name"] == "Biology"
    assert j["deck"]["total_cards"] == 2
    assert j["deck"]["cards"][0]["tags"] == ["bio"]
    assert _deck_count(client) == 1


def test_import_quizlet_text(client):
    r = client.post(
        "/api/learning/import",
        data={"deck_title": "Terms", "text": "cat\tgato\ndog\tperro\nbad line", "format": "quizlet"},
    )
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["imported"] == 2 and j["skipped"] == 1
    assert j["deck"]["cards"][1]["back"] == "perro"
    assert _deck_count(client) == 1


def test_quizlet_custom_separators(client):
    r = client.post(
        "/api/learning/import/preview",
        data={"text": "a=1;b=2", "format": "quizlet", "term_sep": "=", "row_sep": ";"},
    )
    assert r.status_code == 200
    assert r.json()["total"] == 2


@pytest.mark.parametrize("path,extra", [("/api/learning/import/preview", {}), ("/api/learning/import", {"deck_title": "X"})])
def test_empty_input_422(client, path, extra):
    r = client.post(path, data={"text": "   ", **extra})
    assert r.status_code == 422
    assert "file or pasted text" in r.json()["detail"]
    assert _deck_count(client) == 0


def test_garbage_apkg_422(client):
    r = client.post(
        "/api/learning/import/preview",
        data={"format": "apkg"},
        files={"file": ("bad.apkg", b"not a zip", "application/octet-stream")},
    )
    assert r.status_code == 422
    assert r.json()["detail"]


def test_import_no_cards_422(client):
    r = client.post("/api/learning/import", data={"deck_title": "X", "text": "no separators here"})
    assert r.status_code == 422
    assert _deck_count(client) == 0


def test_oversized_413(client, monkeypatch):
    monkeypatch.setattr(learning_router, "MAX_IMPORT_BYTES", 10)
    for path, extra in [("/api/learning/import/preview", {}), ("/api/learning/import", {"deck_title": "X"})]:
        r = client.post(path, data=extra, files={"file": ("a.txt", b"x" * 50, "text/plain")})
        assert r.status_code == 413
    assert _deck_count(client) == 0


def test_unknown_format_422(client):
    r = client.post("/api/learning/import/preview", data={"text": "a\tb", "format": "zip"})
    assert r.status_code == 422


def test_deck_routes_not_shadowed(client):
    assert client.get("/api/learning/decks").status_code == 200
