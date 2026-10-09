"""Scholarship tracker: summary + CSV import (/api/applications/scholarships/*)."""
from datetime import date, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.routers import applications as applications_router
from backend.routers import documents as documents_router


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("ACADEMIC_OS_DATA", str(tmp_path))
    applications_router.reset_service()
    documents_router._service = None
    app = FastAPI()
    app.include_router(applications_router.router)
    app.include_router(documents_router.router)
    with TestClient(app) as c:
        yield c
    applications_router.reset_service()
    documents_router._service = None


def _sch(client, **kw):
    body = {"name": "Aid", "type": "scholarship"}
    body.update(kw)
    r = client.post("/api/applications", json=body)
    assert r.status_code == 200, r.text
    return r.json()["item"]


def _iso(days):
    return (date.today() + timedelta(days=days)).isoformat()


def _csv(client, text, **params):
    return client.post(
        "/api/applications/scholarships/import-csv",
        params=params,
        files={"file": ("s.csv", text.encode(), "text/csv")},
    )


def test_new_fields_default_and_roundtrip(client):
    a = _sch(client)
    assert a["renewable"] is False and a["awarded_amount"] is None and a["eligibility"] == ""
    r = client.patch(f"/api/applications/{a['id']}", json={"renewable": True, "awarded_amount": 500, "eligibility": "STEM"})
    assert r.json()["item"]["awarded_amount"] == 500
    assert client.patch(f"/api/applications/{a['id']}", json={"awarded_amount": -1}).status_code == 422


def test_old_record_loads():
    from backend.services.applications import Application

    app = Application.from_dict({"id": "x", "name": "n", "bogus": 1})
    assert app.renewable is False and app.awarded_amount is None


def test_summary_math(client):
    _sch(client, name="A", amount=1000, deadline=_iso(10))
    _sch(client, name="B", amount=2000, deadline=_iso(3))
    c = _sch(client, name="C", amount=500)
    client.patch(f"/api/applications/{c['id']}", json={"status": "decision", "decision_result": "accepted", "awarded_amount": 400})
    _sch(client, name="Grad", type="grad", amount=9999)
    s = client.get("/api/applications/scholarships/summary").json()
    assert s["potential_total"] == 3000
    assert s["won_total"] == 400 and s["won_count"] == 1
    assert s["pending_count"] == 2
    assert s["count_by_status"] == {"researching": 2, "decision": 1}
    assert [d["name"] for d in s["next_deadlines"]] == ["B", "A"]
    assert set(s["next_deadlines"][0]) == {"id", "name", "deadline", "amount"}


def test_summary_excludes_archived_and_caps_deadlines(client):
    a = _sch(client, name="Old", amount=100, deadline=_iso(1))
    client.patch(f"/api/applications/{a['id']}", json={"archived": True})
    for i in range(7):
        _sch(client, name=f"S{i}", amount=10, deadline=_iso(i + 2))
    _sch(client, name="Past", amount=10, deadline=_iso(-5))
    s = client.get("/api/applications/scholarships/summary").json()
    assert s["potential_total"] == 80
    assert len(s["next_deadlines"]) == 5
    assert "Old" not in [d["name"] for d in s["next_deadlines"]]
    assert "Past" not in [d["name"] for d in s["next_deadlines"]]


def test_essay_reuse(client):
    doc = client.post("/api/documents", json={"title": "Personal Statement", "kind": "essay"})
    assert doc.status_code == 200, doc.text
    did = doc.json()["item"]["id"]
    _sch(client, name="One", document_ids=[did])
    _sch(client, name="Two", document_ids=[did, "ghost"])
    _sch(client, name="None")
    s = client.get("/api/applications/scholarships/summary").json()
    by = {e["document_id"]: e for e in s["essays"]}
    assert by[did]["title"] == "Personal Statement"
    assert sorted(u["name"] for u in by[did]["used_by"]) == ["One", "Two"]
    assert by["ghost"]["title"] == ""
    assert s["essays"][0]["document_id"] == did


def test_csv_header_variants_and_dates(client):
    text = (
        "Scholarship,Provider,Award,Due Date,Link,Notes,Eligibility,Renewable\n"
        "Alpha,Org1,\"$1,500\",2027-03-01,http://a,n1,GPA 3.5,yes\n"
        "Beta,Org2,200,3/15/2027,,,,\n"
        "Gamma,Org3,,\"March 5, 2027\",,,,no\n"
    )
    r = _csv(client, text).json()
    assert r["created"] == 3 and r["errors"] == [] and r["skipped_duplicates"] == 0
    items = client.get("/api/applications?type=scholarship").json()["items"]
    by = {i["name"]: i for i in items}
    assert by["Alpha"]["amount"] == 1500 and by["Alpha"]["renewable"] is True
    assert by["Alpha"]["eligibility"] == "GPA 3.5" and by["Alpha"]["org"] == "Org1"
    assert by["Beta"]["deadline"] == "2027-03-15"
    assert by["Gamma"]["deadline"] == "2027-03-05" and by["Gamma"]["amount"] is None


def test_csv_other_header_names_and_raw_text_body(client):
    text = "title,org,amount,deadline,url\nX,O,10,2027-01-02,http://x\n"
    r = client.post("/api/applications/scholarships/import-csv", content=text, headers={"content-type": "text/csv"})
    assert r.json()["created"] == 1


def test_csv_duplicates(client):
    _sch(client, name="Dup", org="Org", deadline="2027-03-01")
    text = "name,organization,deadline\nDup,org,2027-03-01\nNew,org,2027-03-01\nNew,org,3/1/2027\n"
    r = _csv(client, text).json()
    assert r["created"] == 1 and r["skipped_duplicates"] == 2


def test_csv_dry_run_saves_nothing(client):
    r = _csv(client, "name,deadline\nA,2027-01-01\n", dry_run="true").json()
    assert r["created"] == 0 and len(r["rows"]) == 1 and r["rows"][0]["name"] == "A"
    assert client.get("/api/applications").json()["count"] == 0


def test_csv_bad_rows_reported_not_fatal(client):
    text = "name,amount,deadline\nGood,5,2027-01-01\n,5,2027-01-01\nBadDate,5,someday\nBadAmt,abc,2027-01-01\nNeg,-4,2027-01-01\n"
    r = _csv(client, text).json()
    assert r["created"] == 1
    assert {e["row"] for e in r["errors"]} == {3, 4, 5, 6}


def test_csv_no_name_column_and_empty(client):
    r = _csv(client, "foo,bar\n1,2\n").json()
    assert r["created"] == 0 and r["errors"]
    r = client.post("/api/applications/scholarships/import-csv", content="", headers={"content-type": "text/csv"})
    assert r.status_code == 422
