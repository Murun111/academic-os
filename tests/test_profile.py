"""Tests for the profile API (/api/profile)."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.routers.profile import router


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("ACADEMIC_OS_DATA", str(tmp_path))
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as c:
        yield c


def test_profile_unset_returns_null_stage(client):
    r = client.get("/api/profile")
    assert r.status_code == 200
    assert r.json() == {"stage": None, "name": ""}


def test_profile_set_and_get_roundtrip(client):
    r = client.put("/api/profile", json={"stage": "grad", "name": "Sam"})
    assert r.status_code == 200
    assert r.json()["stage"] == "grad"
    r = client.get("/api/profile")
    assert r.json() == {"stage": "grad", "name": "Sam"}


def test_profile_stage_change(client):
    client.put("/api/profile", json={"stage": "highschool"})
    client.put("/api/profile", json={"stage": "undergrad"})
    assert client.get("/api/profile").json()["stage"] == "undergrad"


def test_profile_rejects_bad_stage(client):
    r = client.put("/api/profile", json={"stage": "phd-dropout"})
    assert r.status_code == 422


def test_profile_corrupt_file_tolerated(client, tmp_path):
    (tmp_path / "data").mkdir(exist_ok=True)
    (tmp_path / "data" / "profile.json").write_text("not json{")
    r = client.get("/api/profile")
    assert r.status_code == 200
    assert r.json()["stage"] is None
