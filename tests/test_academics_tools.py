"""Tests for the agent-facing web + academics tools."""
import pytest

from backend.services import academics_tools
from backend.services.autonomy import classify
from backend.services.websearch import _clean, _real_url


# ── autonomy classification ───────────────────────────────────────

def test_web_tools_classified_read():
    assert classify("web.search", {}).decision == "allow"
    assert classify("web.fetch", {}).decision == "allow"
    assert classify("academics.upcoming_deadlines", {}).decision == "allow"
    assert classify("academics.student_profile", {}).decision == "allow"


def test_add_application_is_gated():
    d = classify("academics.add_application", {"name": "X"})
    assert d.decision == "gate"


# ── websearch helpers ─────────────────────────────────────────────

def test_ddg_link_unwrap():
    wrapped = "//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fscholarship&rut=abc"
    assert _real_url(wrapped) == "https://example.com/scholarship"
    assert _real_url("https://plain.example/x") == "https://plain.example/x"


def test_clean_strips_tags_and_entities():
    assert _clean("<b>Gates &amp; Co</b> Scholarship") == "Gates & Co Scholarship"


# ── academics tools ───────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("ACADEMIC_OS_DATA", str(tmp_path))
    academics_tools.reset_services()
    yield
    academics_tools.reset_services()


@pytest.mark.asyncio
async def test_add_application_creates_card():
    result = await academics_tools.add_application(
        name="Test Grant", type="scholarship", deadline="2026-12-01",
        url="https://example.com", notes="amount: $5k")
    assert result["ok"] is True and result["status"] == "researching"
    apps = academics_tools._apps().list_all()
    assert len(apps) == 1
    assert "agent-found" in apps[0].notes  # provenance marker always appended


@pytest.mark.asyncio
async def test_add_application_validates():
    assert (await academics_tools.add_application(name=""))["error"] == "name_required"
    assert (await academics_tools.add_application(name="X", type="phd"))["error"] == "bad_type"


@pytest.mark.asyncio
async def test_student_profile_reads_stage_track(monkeypatch, tmp_path):
    monkeypatch.setenv("ACADEMIC_OS_DATA", str(tmp_path))
    d = tmp_path / "data"
    d.mkdir()
    (d / "profile.json").write_text(
        '{"stage": "gapyear", "name": "Sam", "track": "premed", "test_date": "2027-01-15"}'
    )
    p = await academics_tools.student_profile()
    assert p == {"stage": "gapyear", "track": "premed", "test_date": "2027-01-15"}
    assert "name" not in p  # agents never see the student's name


@pytest.mark.asyncio
async def test_upcoming_deadlines_merges_and_caps():
    # Relative near-future date so the test can't go stale — the deadline
    # filter drops anything before today, and a hardcoded date silently rots.
    import datetime as _dt
    soon = (_dt.date.today() + _dt.timedelta(days=10)).isoformat()
    academics_tools._apps().add(name="Soon Grant", type="scholarship",
                                deadline=soon)
    result = await academics_tools.upcoming_deadlines(days=500)  # capped to 90
    titles = [i["title"] for i in result["items"]]
    assert "Soon Grant" in titles
