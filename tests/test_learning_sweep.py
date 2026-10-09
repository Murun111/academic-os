"""Regression tests for the Learning bug sweep (F26-F35, F92)."""
import threading
from datetime import datetime, timezone
from types import SimpleNamespace as NS

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.routers import learning as learning_router
from backend.services import learning_ai
from backend.services.deck_import import parse_delimited, parse_quizlet_text
from backend.services.srs_engine import calculate_next_review


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr("backend.vault.agentic_os_dir", lambda: tmp_path)
    learning_router.reset_service()
    app = FastAPI()
    app.include_router(learning_router.router)
    with TestClient(app) as c:
        yield c
    learning_router.reset_service()


def _deck(client, title="D"):
    return client.post("/api/learning/decks", json={"title": title}).json()["id"]


# F26 ------------------------------------------------------------------
def test_concurrent_card_adds_are_all_stored(client):
    did = _deck(client)
    codes: list[int] = []

    def add(i):
        r = client.post(f"/api/learning/decks/{did}/cards", json={"front": f"q{i}", "back": f"a{i}"})
        codes.append(r.status_code)

    threads = [threading.Thread(target=add, args=(i,)) for i in range(30)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert codes == [200] * 30
    assert len(client.get(f"/api/learning/decks/{did}").json()["cards"]) == 30


# F28 / F30 ------------------------------------------------------------
def test_empty_concept_falls_back_to_topic_and_updates_mastery(client):
    q = {"prompt": "p", "type": "short_answer", "correct_answer": "x", "concept": ""}
    quiz = client.post("/api/learning/quizzes", json={"title": "T", "topic": "Krebs", "questions": [q]}).json()
    assert quiz["questions"][0]["concept"] == "Krebs"
    # an old stored quiz with an empty concept still feeds mastery
    from backend.services.learning import LearningService
    svc = learning_router.get_service()
    quizzes = svc._read_jsonl(svc.quizzes_file)
    quizzes[0]["questions"][0]["concept"] = ""
    svc._write_jsonl(svc.quizzes_file, quizzes)
    qid = quiz["questions"][0]["id"]
    client.post(f"/api/learning/quizzes/{quiz['id']}/submit", json={"answers": {qid: "x"}})
    topics = client.get("/api/learning/mastery").json()["topics"]
    assert [t["name"] for t in topics] == ["Krebs"]


def test_manual_mastery_status_survives_a_quiz_result(client):
    t = client.post("/api/learning/mastery/topics", json={"name": "Krebs", "status": "mastered"}).json()
    q = {"prompt": "p", "type": "short_answer", "correct_answer": "x", "concept": "Krebs"}
    quiz = client.post("/api/learning/quizzes", json={"title": "T", "topic": "Krebs", "questions": [q]}).json()
    qid = quiz["questions"][0]["id"]
    client.post(f"/api/learning/quizzes/{quiz['id']}/submit", json={"answers": {qid: "wrong"}})
    topics = client.get("/api/learning/mastery").json()["topics"]
    assert topics[0]["id"] == t["id"] and topics[0]["status"] == "mastered"
    # after 3 results since the manual set, accuracy takes over again
    for _ in range(2):
        client.post(f"/api/learning/quizzes/{quiz['id']}/submit", json={"answers": {qid: "wrong"}})
    assert client.get("/api/learning/mastery").json()["topics"][0]["status"] == "needs_review"


# F31 ------------------------------------------------------------------
def test_patch_can_clear_course_and_blank_titles_rejected(client):
    did = client.post("/api/learning/decks", json={"title": "D", "course_id": "c1", "course_name": "Bio"}).json()["id"]
    r = client.patch(f"/api/learning/decks/{did}", json={"course_id": None, "course_name": None})
    assert r.status_code == 200 and r.json()["course_id"] is None and r.json()["course_name"] is None
    assert client.patch(f"/api/learning/decks/{did}", json={"title": "   "}).status_code == 422
    assert client.post("/api/learning/decks", json={"title": "   "}).status_code == 422
    assert client.post(f"/api/learning/decks/{did}/cards", json={"front": " ", "back": "b"}).status_code == 422
    assert client.post("/api/learning/focus", json={"duration_minutes": -500, "topic": "t"}).status_code == 422
    assert client.post("/api/learning/focus", json={"duration_minutes": 25, "topic": "t"}).status_code == 200


# F34 ------------------------------------------------------------------
def test_due_cards_limit_and_bulk_add(client):
    did = _deck(client)
    r = client.post(f"/api/learning/decks/{did}/cards/bulk",
                    json={"cards": [{"front": f"q{i}", "back": "a"} for i in range(5)]})
    assert r.status_code == 200 and len(r.json()["cards"]) == 5
    assert len(client.get("/api/learning/due-cards").json()) == 5
    assert len(client.get("/api/learning/due-cards?limit=2").json()) == 2
    bad = client.post(f"/api/learning/decks/{did}/cards/bulk", json={"cards": [{"front": "q", "back": "a"}, {"front": " ", "back": "a"}]})
    assert bad.status_code == 422
    assert len(client.get(f"/api/learning/decks/{did}").json()["cards"]) == 5  # all or nothing
    assert client.post("/api/learning/decks/nope/cards/bulk", json={"cards": [{"front": "q", "back": "a"}]}).status_code == 404


# F35 ------------------------------------------------------------------
def test_next_review_snaps_to_local_midnight_and_hard_grows():
    now = datetime(2026, 10, 9, 20, 30, tzinfo=timezone.utc)
    out = calculate_next_review("good", repetition=1, interval_days=1, now=now)
    nxt = datetime.fromisoformat(out["next_review"]).astimezone()
    assert (nxt.hour, nxt.minute, nxt.second) == (0, 0, 0)
    assert (nxt.date() - now.astimezone().date()).days == out["interval_days"] == 6
    for i in (1, 2, 3, 4):
        assert calculate_next_review("hard", repetition=2, interval_days=i, now=now)["interval_days"] > i


# F27 / F33 ------------------------------------------------------------
def test_csv_without_front_back_header_is_sniffed():
    r = parse_delimited("term,definition\nmitosis,cell division\nmeiosis,gamete formation")
    assert [c["front"] for c in r.cards] == ["mitosis", "meiosis"]
    r = parse_delimited("mitosis,cell division\nmeiosis,gametes")
    assert len(r.cards) == 2 and r.skipped == 0
    r = parse_delimited("a;b\nc;d")
    assert len(r.cards) == 2
    r = parse_delimited("only one column\nanother")
    assert r.cards == [] and r.warnings


def test_import_truncation_warns_and_single_line_semicolon_is_one_row():
    r = parse_quizlet_text("t\t" + "x" * 5000)
    assert len(r.cards[0]["back"]) == 2000 and any("2000" in w for w in r.warnings)
    r = parse_quizlet_text("Mitosis - cell division; produces two cells", "auto", "auto")
    assert len(r.cards) == 1 and r.skipped == 0 and r.cards[0]["back"].endswith("two cells")
    r = parse_quizlet_text("a - b; c - d", "auto", "auto")
    assert len(r.cards) == 2


# F32 ------------------------------------------------------------------
def test_extract_json_with_inner_code_fences():
    ex = learning_ai._extract_json_block
    fenced = '```json\n[{"front": "q", "back": "```python\\nprint(1)\\n```"}]\n```'
    assert ex(fenced)[0]["back"].startswith("```python")
    assert ex('{"summary_markdown": "x ```py\\nq\\n``` y"}')["summary_markdown"].startswith("x ```py")
    assert ex('["Use ```x = [1,2]``` here"]') == ["Use ```x = [1,2]``` here"]
    assert ex("Sure!\n```json\n[1, 2]\n```\nbye") == [1, 2]


# F92 ------------------------------------------------------------------
@pytest.mark.asyncio
async def test_hub_chat_never_uses_cloud_backends(monkeypatch):
    called = []

    class Cloud:
        async def models(self):
            return [NS(id="c")]

        async def chat(self, messages, model_id):
            called.append(model_id)
            return NS(content="leaked")

    async def only_cloud():
        return {"ollama": NS(online=False, models=[]), "claude": NS(online=True, models=[NS(id="c")]),
                "hermes": NS(online=True, models=[])}
    monkeypatch.setattr(learning_ai, "status_all", only_cloud)
    monkeypatch.setattr(learning_ai, "get_backend", lambda name: Cloud())
    assert await learning_ai._hub_chat([]) is None
    assert called == []
