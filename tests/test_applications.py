"""Tests for the Applications Pipeline module (/api/applications/*)."""
from datetime import date, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.routers import applications as applications_router


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("ACADEMIC_OS_DATA", str(tmp_path))
    applications_router.reset_service()
    app = FastAPI()
    app.include_router(applications_router.router)
    with TestClient(app) as c:
        yield c
    applications_router.reset_service()


def _create(client, **overrides):
    body = {"name": "Stanford MS CS", "type": "grad"}
    body.update(overrides)
    return client.post("/api/applications", json=body)


# === CRUD ===


def test_create_application(client):
    r = _create(client)
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    item = body["item"]
    assert item["name"] == "Stanford MS CS"
    assert item["type"] == "grad"
    assert item["status"] == "researching"
    assert item["decision_result"] == ""
    assert item["requirements"] == []
    assert item["id"]


def test_create_requires_name_and_type(client):
    r = client.post("/api/applications", json={"type": "grad"})
    assert r.status_code == 422  # pydantic: name missing

    r2 = client.post("/api/applications", json={"name": "Fulbright", "type": "bogus"})
    assert r2.status_code == 422  # service: bad enum


def test_list_applications(client):
    _create(client, name="A", type="grad")
    _create(client, name="B", type="scholarship")
    r = client.get("/api/applications")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 2
    assert len(body["items"]) == 2


def test_list_filters_by_type_and_status(client):
    _create(client, name="A", type="grad")
    _create(client, name="B", type="scholarship")
    r = client.get("/api/applications?type=grad")
    assert r.status_code == 200
    assert r.json()["count"] == 1
    assert r.json()["items"][0]["name"] == "A"

    r2 = client.get("/api/applications?status=researching")
    assert r2.json()["count"] == 2

    r3 = client.get("/api/applications?type=bogus")
    assert r3.status_code == 422


def test_get_application(client):
    item_id = _create(client).json()["item"]["id"]
    r = client.get(f"/api/applications/{item_id}")
    assert r.status_code == 200
    assert r.json()["item"]["id"] == item_id


def test_get_application_missing_returns_404(client):
    r = client.get("/api/applications/nope")
    assert r.status_code == 404


def test_delete_application(client):
    item_id = _create(client).json()["item"]["id"]
    r = client.delete(f"/api/applications/{item_id}")
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert client.get(f"/api/applications/{item_id}").status_code == 404


def test_delete_missing_returns_404(client):
    r = client.delete("/api/applications/nope")
    assert r.status_code == 404


# === status transitions ===


def test_status_transition_via_patch(client):
    item_id = _create(client).json()["item"]["id"]
    r = client.patch(f"/api/applications/{item_id}", json={"status": "submitted"})
    assert r.status_code == 200
    assert r.json()["item"]["status"] == "submitted"

    r2 = client.patch(
        f"/api/applications/{item_id}",
        json={"status": "decision", "decision_result": "accepted"},
    )
    assert r2.status_code == 200
    assert r2.json()["item"]["status"] == "decision"
    assert r2.json()["item"]["decision_result"] == "accepted"


def test_patch_rejects_bad_enum(client):
    item_id = _create(client).json()["item"]["id"]
    r = client.patch(f"/api/applications/{item_id}", json={"status": "not_a_status"})
    assert r.status_code == 422

    r2 = client.patch(f"/api/applications/{item_id}", json={"type": "not_a_type"})
    assert r2.status_code == 422

    r3 = client.patch(f"/api/applications/{item_id}", json={"decision_result": "maybe"})
    assert r3.status_code == 422


def test_patch_missing_id_returns_404(client):
    r = client.patch("/api/applications/nope", json={"status": "submitted"})
    assert r.status_code == 404


# === requirements ===


def test_requirement_add_toggle_delete_roundtrip(client):
    item_id = _create(client).json()["item"]["id"]

    r = client.post(f"/api/applications/{item_id}/requirements", json={"label": "Transcript"})
    assert r.status_code == 200
    item = r.json()["item"]
    assert len(item["requirements"]) == 1
    req = item["requirements"][0]
    assert req["label"] == "Transcript"
    assert req["done"] is False
    rid = req["id"]

    r2 = client.patch(
        f"/api/applications/{item_id}/requirements/{rid}", json={"done": True}
    )
    assert r2.status_code == 200
    toggled = next(x for x in r2.json()["item"]["requirements"] if x["id"] == rid)
    assert toggled["done"] is True

    r3 = client.delete(f"/api/applications/{item_id}/requirements/{rid}")
    assert r3.status_code == 200
    assert r3.json()["item"]["requirements"] == []


def test_requirement_add_missing_application_returns_404(client):
    r = client.post("/api/applications/nope/requirements", json={"label": "x"})
    assert r.status_code == 404


def test_requirement_toggle_missing_requirement_returns_404(client):
    item_id = _create(client).json()["item"]["id"]
    r = client.patch(
        f"/api/applications/{item_id}/requirements/nope", json={"done": True}
    )
    assert r.status_code == 404


# === deadlines ===


def test_upcoming_deadlines_excludes_past_and_decision_sorted_ascending(client):
    today = date.today()
    past = (today - timedelta(days=1)).isoformat()
    soon = (today + timedelta(days=5)).isoformat()
    later = (today + timedelta(days=10)).isoformat()
    far = (today + timedelta(days=100)).isoformat()

    _create(client, name="Past deadline", deadline=past)
    later_id = _create(client, name="Later", deadline=later).json()["item"]["id"]
    soon_id = _create(client, name="Soon", deadline=soon).json()["item"]["id"]
    _create(client, name="Far future", deadline=far)
    decided_id = _create(client, name="Already decided", deadline=soon).json()["item"]["id"]
    client.patch(f"/api/applications/{decided_id}", json={"status": "decision"})

    r = client.get("/api/applications/deadlines?days=30")
    assert r.status_code == 200
    body = r.json()
    ids = [i["id"] for i in body["items"]]
    assert ids == [soon_id, later_id]  # ascending, excludes past/far/decision
    assert body["count"] == 2


# === money fields ===


def test_money_fields_round_trip_via_post(client):
    r = _create(client, amount=5000, app_fee=75, fee_waived=False)
    assert r.status_code == 200
    item = r.json()["item"]
    assert item["amount"] == 5000
    assert item["app_fee"] == 75
    assert item["fee_waived"] is False


def test_money_fields_round_trip_via_patch(client):
    item_id = _create(client).json()["item"]["id"]
    r = client.patch(
        f"/api/applications/{item_id}",
        json={"amount": 2500.5, "app_fee": 50, "fee_waived": True},
    )
    assert r.status_code == 200
    item = r.json()["item"]
    assert item["amount"] == 2500.5
    assert item["app_fee"] == 50
    assert item["fee_waived"] is True


def test_negative_amount_returns_422(client):
    r = _create(client, amount=-10)
    assert r.status_code == 422

    r2 = _create(client, app_fee=-5)
    assert r2.status_code == 422

    item_id = _create(client).json()["item"]["id"]
    r3 = client.patch(f"/api/applications/{item_id}", json={"amount": -1})
    assert r3.status_code == 422


# === costs ===


def test_costs_math_with_seeded_mix(client):
    # scholarship, still open, potential award
    _create(client, name="Fulbright", type="scholarship", amount=10000, app_fee=0)
    # scholarship, accepted -> won award, no longer "potential" (decision status)
    won_id = _create(
        client, name="Rhodes", type="scholarship", amount=20000, app_fee=25,
    ).json()["item"]["id"]
    client.patch(
        f"/api/applications/{won_id}",
        json={"status": "decision", "decision_result": "accepted"},
    )
    # grad app with a fee, fee not waived, still owed
    _create(client, name="MIT", type="grad", app_fee=100, fee_waived=False)
    # grad app with a fee, waived
    _create(client, name="Berkeley", type="grad", app_fee=90, fee_waived=True)
    # decision-stage app with unwaived fee -> excluded from fees_due
    decided_id = _create(
        client, name="CMU", type="grad", app_fee=80, fee_waived=False,
    ).json()["item"]["id"]
    client.patch(f"/api/applications/{decided_id}", json={"status": "decision"})
    # no money fields at all -> nulls count as 0
    _create(client, name="Nowhere", type="undergrad")

    r = client.get("/api/applications/costs")
    assert r.status_code == 200
    body = r.json()

    assert body["fees_due"] == 100  # MIT only; Berkeley waived, CMU decided
    assert body["fees_waived"] == 90  # Berkeley
    assert body["potential_awards"] == 10000  # Fulbright only; Rhodes is decided
    assert body["won_awards"] == 20000  # Rhodes accepted

    by_type = body["by_type"]
    assert by_type["scholarship"]["count"] == 2
    assert by_type["scholarship"]["amount"] == 30000
    assert by_type["grad"]["count"] == 3
    assert by_type["grad"]["amount"] == 0
    assert by_type["undergrad"]["count"] == 1
    assert by_type["undergrad"]["amount"] == 0


def test_costs_route_not_shadowed_by_id_route(client):
    r = client.get("/api/applications/costs")
    assert r.status_code == 200
    body = r.json()
    assert body["fees_due"] == 0
    assert body["fees_waived"] == 0
    assert body["potential_awards"] == 0
    assert body["won_awards"] == 0
    assert body["by_type"] == {}
