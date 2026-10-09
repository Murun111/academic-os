import pytest
from datetime import datetime, timezone
from pathlib import Path
from fastapi.testclient import TestClient

from backend.app import app
from backend.routers.learning import reset_service
from backend.services.srs_engine import calculate_next_review, initial_srs_state
from backend.services.learning import LearningService


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr("backend.vault.agentic_os_dir", lambda: tmp_path)
    reset_service()
    with TestClient(app) as c:
        yield c
    reset_service()


def test_srs_engine_sm2_progression():
    state = initial_srs_state()
    assert state["repetition"] == 0
    assert state["interval_days"] == 0
    assert state["ease_factor"] == 2.5

    # First review: Good (rating="good")
    res1 = calculate_next_review(rating="good", current_ease=state["ease_factor"], repetition=state["repetition"], interval_days=state["interval_days"])
    assert res1["repetition"] == 1
    assert res1["interval_days"] == 1
    assert res1["ease_factor"] == 2.5

    # Second review: Good
    res2 = calculate_next_review(rating="good", current_ease=res1["ease_factor"], repetition=res1["repetition"], interval_days=res1["interval_days"])
    assert res2["repetition"] == 2
    assert res2["interval_days"] == 6

    # Third review: Good
    res3 = calculate_next_review(rating="good", current_ease=res2["ease_factor"], repetition=res2["repetition"], interval_days=res2["interval_days"])
    assert res3["repetition"] == 3
    assert res3["interval_days"] == 15  # 6 * 2.5 = 15

    # Fourth review: Again (Failure)
    res_fail = calculate_next_review(rating="again", current_ease=res3["ease_factor"], repetition=res3["repetition"], interval_days=res3["interval_days"])
    assert res_fail["repetition"] == 0
    assert res_fail["interval_days"] == 1
    assert res_fail["lapses"] == 1


def test_learning_decks_and_cards_api(client: TestClient):
    # Overview empty initially
    res = client.get("/api/learning/overview")
    assert res.status_code == 200
    assert res.json()["total_cards"] == 0
    assert res.json()["cards_due_today"] == 0

    # Create Deck
    deck_data = {
        "title": "Cell Biology",
        "description": "Key organelles and cell processes",
        "course_name": "BIO 101",
        "tags": ["Biology", "Cells"],
        "cards": [
            {
                "front": "What organelle produces ATP?",
                "back": "Mitochondria",
                "hint": "Powerhouse",
                "explanation": "Generates ATP through oxidative phosphorylation.",
            }
        ]
    }
    create_res = client.post("/api/learning/decks", json=deck_data)
    assert create_res.status_code == 200
    deck = create_res.json()
    deck_id = deck["id"]
    assert deck["total_cards"] == 1
    assert deck["due_cards"] == 1

    # Add second card
    card_res = client.post(f"/api/learning/decks/{deck_id}/cards", json={
        "front": "Where does photosynthesis occur?",
        "back": "Chloroplasts",
        "hint": "Green organelle",
        "explanation": "Thylakoid membranes contain chlorophyll.",
    })
    assert card_res.status_code == 200
    card = card_res.json()
    card_id = card["id"]

    # Get due cards
    due_res = client.get(f"/api/learning/due-cards?deck_id={deck_id}")
    assert due_res.status_code == 200
    due_cards = due_res.json()
    assert len(due_cards) == 2

    # Review card 2 as Good
    rev_res = client.post(f"/api/learning/decks/{deck_id}/cards/{card_id}/review", json={"rating": "good"})
    assert rev_res.status_code == 200
    rev_card = rev_res.json()
    assert rev_card["srs"]["repetition"] == 1
    assert rev_card["srs"]["interval_days"] == 1

    # Overview updated
    overview = client.get("/api/learning/overview").json()
    assert overview["total_cards"] == 2
    assert overview["total_decks"] == 1


def test_learning_quiz_flow_and_mastery(client: TestClient):
    quiz_data = {
        "title": "Linear Algebra Basics",
        "topic": "Matrices and Vectors",
        "course_name": "MATH 201",
        "time_limit_mins": 10,
        "questions": [
            {
                "id": "q1",
                "prompt": "What is the determinant of an identity matrix?",
                "type": "multiple_choice",
                "options": ["0", "1", "-1", "Undefined"],
                "correct_answer": "1",
                "explanation": "The determinant of any identity matrix I_n is 1.",
                "concept": "Matrix Determinants",
            },
            {
                "id": "q2",
                "prompt": "True or False: If det(A) = 0, matrix A is invertible.",
                "type": "true_false",
                "options": ["True", "False"],
                "correct_answer": "False",
                "explanation": "A matrix is invertible if and only if its determinant is non-zero.",
                "concept": "Matrix Invertibility",
            }
        ]
    }
    create_quiz = client.post("/api/learning/quizzes", json=quiz_data)
    assert create_quiz.status_code == 200
    quiz = create_quiz.json()
    quiz_id = quiz["id"]

    # Submit answers (q1 correct, q2 wrong)
    sub_res = client.post(f"/api/learning/quizzes/{quiz_id}/submit", json={
        "answers": {
            "q1": "1",
            "q2": "True",
        },
        "time_spent_secs": 45
    })
    assert sub_res.status_code == 200
    attempt = sub_res.json()
    assert attempt["score"] == 50.0
    assert attempt["correct_count"] == 1
    assert attempt["total_questions"] == 2

    # Check mastery matrix automatically recorded concepts
    mastery_res = client.get("/api/learning/mastery")
    assert mastery_res.status_code == 200
    mastery = mastery_res.json()
    topics = {t["name"]: t for t in mastery["topics"]}
    assert "Matrix Determinants" in topics
    assert "Matrix Invertibility" in topics
    assert topics["Matrix Determinants"]["status"] == "proficient"
    assert topics["Matrix Invertibility"]["status"] == "developing"


def test_study_guides_and_focus_sessions(client: TestClient):
    # Create study guide
    guide_res = client.post("/api/learning/guides", json={
        "title": "Quantum Mechanics Quick Notes",
        "topic": "Schrödinger Equation",
        "content": "## Time-dependent wave equation\n- i*hbar * d(psi)/dt = H(psi)",
        "key_takeaways": ["Wave-particle duality", "Normalization of state vector"],
        "formulas": ["E = h*f", "p = h/lambda"],
        "tags": ["Physics", "Quantum"],
    })
    assert guide_res.status_code == 200
    guide_id = guide_res.json()["id"]

    guides_list = client.get("/api/learning/guides").json()
    assert len(guides_list) == 1
    assert guides_list[0]["id"] == guide_id

    # Log focus session
    focus_res = client.post("/api/learning/focus", json={
        "duration_minutes": 25,
        "topic": "Quantum Wavefunctions",
        "goal": "Derive particle in a 1D box",
        "reflections": "Understood boundary conditions at x=0 and x=L.",
    })
    assert focus_res.status_code == 200
    assert focus_res.json()["duration_minutes"] == 25

    # Check overview
    overview = client.get("/api/learning/overview").json()
    assert overview["total_focus_minutes"] == 25


# ── Added coverage: review edge cases, CRUD errors, AI endpoints ─────────
def _mk_deck(client: TestClient) -> tuple[str, str]:
    deck = client.post("/api/learning/decks", json={
        "title": "D", "cards": [{"front": "f", "back": "b"}],
    }).json()
    return deck["id"], deck["cards"][0]["id"] if "cards" in deck else client.get(
        f"/api/learning/decks/{deck['id']}").json()["cards"][0]["id"]


def test_review_endpoint_ratings_and_errors(client: TestClient):
    deck_id, card_id = _mk_deck(client)
    url = f"/api/learning/decks/{deck_id}/cards/{card_id}/review"

    good = client.post(url, json={"rating": "good"}).json()
    assert good["srs"]["repetition"] == 1
    again = client.post(url, json={"rating": "again"}).json()
    assert again["srs"]["repetition"] == 0
    assert again["srs"]["lapses"] == 1
    assert again["srs"]["interval_days"] == 1

    assert client.post(url, json={"rating": "bogus"}).status_code == 422
    assert client.post(url, json={}).status_code == 422
    assert client.post(f"/api/learning/decks/{deck_id}/cards/nope/review", json={"rating": "good"}).status_code == 404
    assert client.post(f"/api/learning/decks/nope/cards/{card_id}/review", json={"rating": "good"}).status_code == 404


def test_reviewed_card_leaves_due_queue(client: TestClient):
    deck_id, card_id = _mk_deck(client)
    assert len(client.get("/api/learning/due-cards").json()) == 1
    client.post(f"/api/learning/decks/{deck_id}/cards/{card_id}/review", json={"rating": "good"})
    assert client.get(f"/api/learning/due-cards?deck_id={deck_id}").json() == []


def test_deck_card_quiz_guide_not_found_and_delete(client: TestClient):
    assert client.get("/api/learning/decks/nope").status_code == 404
    assert client.patch("/api/learning/decks/nope", json={"title": "x"}).status_code == 404
    assert client.delete("/api/learning/decks/nope").status_code == 404
    assert client.get("/api/learning/quizzes/nope").status_code == 404
    assert client.delete("/api/learning/quizzes/nope").status_code == 404
    assert client.post("/api/learning/quizzes/nope/submit", json={"answers": {}}).status_code == 404
    assert client.get("/api/learning/guides/nope").status_code == 404
    assert client.delete("/api/learning/guides/nope").status_code == 404
    assert client.patch("/api/learning/mastery/topics/nope", json={"status": "proficient"}).status_code == 404

    deck_id, card_id = _mk_deck(client)
    assert client.patch(f"/api/learning/decks/{deck_id}", json={"title": "Renamed"}).json()["title"] == "Renamed"
    assert client.delete(f"/api/learning/decks/{deck_id}/cards/{card_id}").status_code == 200
    assert client.delete(f"/api/learning/decks/{deck_id}/cards/{card_id}").status_code == 404
    assert client.delete(f"/api/learning/decks/{deck_id}").status_code == 200
    assert client.get(f"/api/learning/decks/{deck_id}").status_code == 404


def test_mastery_topic_endpoints(client: TestClient):
    r = client.post("/api/learning/mastery/topics", json={"name": "Limits"})
    assert r.status_code == 200
    tid = r.json()["id"]
    upd = client.patch(f"/api/learning/mastery/topics/{tid}", json={"status": "proficient"})
    assert upd.status_code == 200
    assert upd.json()["status"] == "proficient"
    names = {t["name"] for t in client.get("/api/learning/mastery").json()["topics"]}
    assert "Limits" in names


def test_focus_list_and_quiz_list(client: TestClient):
    client.post("/api/learning/focus", json={"duration_minutes": 10, "topic": "t"})
    assert len(client.get("/api/learning/focus").json()) == 1
    assert client.get("/api/learning/quizzes").json() == []


def _patch_chat(monkeypatch, value):
    async def fake(messages):
        if isinstance(value, Exception):
            raise value
        return value
    monkeypatch.setattr("backend.services.learning_ai._hub_chat", fake)


_AI_CALLS = [
    ("/api/learning/generate/flashcards", {"topic": "Thermo", "count": 3}),
    ("/api/learning/generate/quiz", {"topic": "Thermo", "num_questions": 2}),
    ("/api/learning/generate/guide", {"topic": "Thermo"}),
    ("/api/learning/tutor", {"topic": "Thermo", "messages": [{"role": "user", "content": "why?"}]}),
]


def test_ai_endpoints_503_when_llm_unreachable(client: TestClient, monkeypatch):
    # No LLM online: 503 with a readable detail, never fabricated template content.
    _patch_chat(monkeypatch, None)
    for url, body in _AI_CALLS:
        r = client.post(url, json=body)
        assert r.status_code == 503, url
        assert "AI model" in r.json()["detail"]


def test_ai_endpoints_503_when_llm_raises(client: TestClient, monkeypatch):
    _patch_chat(monkeypatch, RuntimeError("boom"))
    for url, body in _AI_CALLS:
        assert client.post(url, json=body).status_code == 503, url


def test_ai_generate_502_on_unparseable_output(client: TestClient, monkeypatch):
    _patch_chat(monkeypatch, "sorry, I can't do JSON")
    for url, body in _AI_CALLS[:3]:
        assert client.post(url, json=body).status_code == 502, url


def test_ai_output_normalized_to_contract(client: TestClient, monkeypatch):
    import json as _json
    # Guide missing arrays (seen live from qwen2.5:7b) must come back with empty lists, not absent keys.
    _patch_chat(monkeypatch, _json.dumps({"title": "G", "summary_markdown": "## s"}))
    g = client.post("/api/learning/generate/guide", json={"topic": "T"}).json()["guide_data"]
    assert g["key_takeaways"] == [] and g["formulas"] == [] and g["tags"] == []
    # Ungradeable questions (answer not among options) and cards without a back are dropped.
    _patch_chat(monkeypatch, _json.dumps([
        {"prompt": "ok", "type": "multiple_choice", "options": ["a", "b"], "correct_answer": "a"},
        {"prompt": "bad", "type": "multiple_choice", "options": ["a", "b"], "correct_answer": "z"},
        {"prompt": "tf", "type": "true_false", "correct_answer": "True"},
    ]))
    qs = client.post("/api/learning/generate/quiz", json={"topic": "T"}).json()["questions"]
    assert [q["prompt"] for q in qs] == ["ok", "tf"] and qs[1]["options"] == ["True", "False"]
    _patch_chat(monkeypatch, _json.dumps([{"front": "Q"}, {"front": "Q2", "back": "A2", "tags": "x"}]))
    cards = client.post("/api/learning/generate/flashcards", json={"topic": "T"}).json()["cards"]
    assert len(cards) == 1 and cards[0]["tags"] == ["x"] and cards[0]["hint"] == ""


def test_ai_failure_saves_nothing(client: TestClient, monkeypatch):
    _patch_chat(monkeypatch, None)
    before = len(client.get("/api/learning/decks").json())
    r = client.post("/api/learning/generate/flashcards", json={"topic": "T", "save_to_deck": True})
    assert r.status_code == 503
    assert len(client.get("/api/learning/decks").json()) == before


def test_ai_generate_uses_llm_output_and_saves(client: TestClient, monkeypatch):
    import json as _json
    _patch_chat(monkeypatch, "```json\n" + _json.dumps(
        [{"front": "Q?", "back": "A", "hint": "", "explanation": "", "tags": ["t"]}]) + "\n```")
    r = client.post("/api/learning/generate/flashcards",
                    json={"topic": "T", "save_to_deck": True, "deck_title": "Saved"})
    assert r.status_code == 200
    assert r.json()["cards"][0]["front"] == "Q?"
    assert r.json()["deck"]["title"] == "Saved"
    assert r.json()["deck"]["total_cards"] == 1

    _patch_chat(monkeypatch, _json.dumps([{
        "prompt": "p", "type": "true_false", "options": ["True", "False"],
        "correct_answer": "True", "explanation": "e", "concept": "c"}]))
    r = client.post("/api/learning/generate/quiz", json={"topic": "T", "save_as_quiz": True})
    assert r.status_code == 200 and r.json()["quiz"] is not None

    _patch_chat(monkeypatch, _json.dumps({
        "title": "G", "summary_markdown": "## s", "key_takeaways": ["k"], "formulas": [], "tags": []}))
    r = client.post("/api/learning/generate/guide", json={"topic": "T", "save_as_guide": True})
    assert r.status_code == 200 and r.json()["guide"]["title"] == "G"

    _patch_chat(monkeypatch, "What do you think?")
    r = client.post("/api/learning/tutor", json={"topic": "T", "messages": [{"role": "user", "content": "hi"}]})
    assert r.json()["reply"] == "What do you think?"


def test_ai_endpoints_validate_body(client: TestClient):
    assert client.post("/api/learning/generate/flashcards", json={}).status_code == 422
    assert client.post("/api/learning/tutor", json={"topic": "x"}).status_code == 422


@pytest.mark.asyncio
async def test_hub_chat_selects_online_backend_and_none_when_offline(monkeypatch):
    from types import SimpleNamespace as NS
    from backend.services import learning_ai

    async def offline():
        return {"ollama": NS(online=False, models=[])}
    monkeypatch.setattr(learning_ai, "status_all", offline)
    assert await learning_ai._hub_chat([]) is None

    class FakeBackend:
        async def models(self):
            return []
        async def chat(self, messages, model_id):
            return NS(content=f"ok:{model_id}")

    async def online():
        return {"a": NS(online=False, models=[]), "b": NS(online=True, models=[NS(id="m1")])}
    monkeypatch.setattr(learning_ai, "status_all", online)
    monkeypatch.setattr(learning_ai, "get_backend", lambda name: FakeBackend())
    assert await learning_ai._hub_chat([]) == "ok:m1"


def test_extract_json_tolerates_small_model_slips():
    # Seen live from qwen2.5:3b: Python triple-quoted strings and raw newlines in JSON strings.
    from backend.services.learning_ai import _extract_json_block
    tq = '{\n "title": "T",\n "summary_markdown": """\n## A\nsays "hi"\n"""\n}'
    assert _extract_json_block(tq) == {"title": "T", "summary_markdown": '## A\nsays "hi"'}
    assert _extract_json_block('{"a": "x\ny"}') == {"a": "x\ny"}


def test_ai_generate_retries_once_on_malformed_output(client: TestClient, monkeypatch):
    import json as _json
    replies = iter(["{broken", _json.dumps({"title": "G", "summary_markdown": "## s"})])
    calls = []

    async def fake(messages):
        calls.append(1)
        return next(replies)
    monkeypatch.setattr("backend.services.learning_ai._hub_chat", fake)
    r = client.post("/api/learning/generate/guide", json={"topic": "T"})
    assert r.status_code == 200 and len(calls) == 2
