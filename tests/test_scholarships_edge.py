"""Edge case tests for scholarship CSV import and summary."""
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


# ===== CSV Import Edge Cases =====

def test_csv_with_bom(client):
    """CSV with UTF-8 BOM should be handled gracefully."""
    text = "﻿name,amount,deadline\nBOM Test,1000,2027-01-01\n"
    r = _csv(client, text).json()
    assert r["created"] == 1 and r["errors"] == []
    items = client.get("/api/applications?type=scholarship").json()["items"]
    assert items[0]["name"] == "BOM Test"


def test_csv_semicolon_delimiter(client):
    """CSV with semicolon delimiter (not auto-detected, should fail or treat as single column)."""
    text = "name;amount;deadline\nSemicolon,1000;2027-01-01\n"
    r = _csv(client, text).json()
    # Standard csv.reader uses comma by default, so semicolons are treated as part of the value
    # This should fail to parse the header or the row correctly
    assert r["created"] == 0 or r["errors"]


def test_csv_quoted_commas_in_names(client):
    """Names with quoted commas should be parsed correctly."""
    text = 'name,org,amount\n"Smith, John",Org A,500\n"Doe, Jane",Org B,750\n'
    r = _csv(client, text).json()
    assert r["created"] == 2 and r["errors"] == []
    items = sorted(client.get("/api/applications?type=scholarship").json()["items"], key=lambda x: x["name"])
    assert items[0]["name"] == "Doe, Jane"
    assert items[1]["name"] == "Smith, John"


def test_csv_amount_with_dollar_and_comma(client):
    """Amounts like $1,500 need to be quoted to preserve the comma."""
    # Unquoted: the comma is treated as a CSV delimiter, breaking the field
    text = "name,amount\nDollar Comma,$1,500\n"
    r = _csv(client, text).json()
    assert r["created"] == 0
    assert any("quote values" in e["message"] for e in r["errors"])
    assert client.get("/api/applications?type=scholarship").json()["items"] == []

    # Properly quoted: preserves the full amount
    text2 = 'name,amount\nQuoted,"$1,500"\n'
    r2 = _csv(client, text2).json()
    assert r2["created"] == 1 and r2["errors"] == []
    items2 = client.get("/api/applications?type=scholarship").json()["items"]
    items2_by_name = {i["name"]: i for i in items2}
    assert items2_by_name["Quoted"]["amount"] == 1500.0


def test_csv_amount_with_decimal(client):
    """Amounts like 1500.00 should be parsed correctly."""
    text = "name,amount\nDecimal,1500.00\n"
    r = _csv(client, text).json()
    assert r["created"] == 1 and r["errors"] == []
    items = client.get("/api/applications?type=scholarship").json()["items"]
    assert items[0]["amount"] == 1500.0


def test_csv_amount_with_k_suffix(client):
    """Amounts like 1.5k should fail (not supported by float conversion)."""
    text = "name,amount\nK Suffix,1.5k\n"
    r = _csv(client, text).json()
    assert r["created"] == 0
    # Should have an error about invalid amount
    assert any("amount" in str(e).lower() for e in r["errors"])


def test_csv_amount_empty(client):
    """Empty amount field should be handled (treated as None)."""
    text = "name,amount,deadline\nEmpty Amt,,2027-01-01\n"
    r = _csv(client, text).json()
    assert r["created"] == 1 and r["errors"] == []
    items = client.get("/api/applications?type=scholarship").json()["items"]
    assert items[0]["amount"] is None


def test_csv_amount_zero(client):
    """Zero amount should be valid."""
    text = "name,amount\nZero,0\n"
    r = _csv(client, text).json()
    assert r["created"] == 1 and r["errors"] == []
    items = client.get("/api/applications?type=scholarship").json()["items"]
    assert items[0]["amount"] == 0.0


def test_csv_date_invalid_month(client):
    """Date like 2026-13-01 (invalid month) should fail."""
    text = "name,deadline\nBad Month,2026-13-01\n"
    r = _csv(client, text).json()
    assert r["created"] == 0
    assert any("deadline" in str(e).lower() or "unparseable" in str(e).lower() for e in r["errors"])


def test_csv_date_invalid_day(client):
    """Date like 2026-02-30 (invalid day) should fail."""
    text = "name,deadline\nBad Day,2026-02-30\n"
    r = _csv(client, text).json()
    assert r["created"] == 0
    assert any("deadline" in str(e).lower() or "unparseable" in str(e).lower() for e in r["errors"])


def test_csv_date_without_year(client):
    """Date like 'Dec 1' without year should fail (ambiguous)."""
    text = "name,deadline\nNo Year,Dec 1\n"
    r = _csv(client, text).json()
    assert r["created"] == 0
    assert any("deadline" in str(e).lower() or "unparseable" in str(e).lower() for e in r["errors"])


def test_csv_date_abbreviated_month(client):
    """Abbreviated month names with comma need to be quoted in CSV."""
    # Unquoted: comma is treated as CSV delimiter, splitting the date
    text = "name,deadline\nUnquoted,Mar 15, 2027\n"
    r = _csv(client, text).json()
    # This fails because "Mar 15" alone can't be parsed as a full date
    assert r["created"] == 0 and len(r["errors"]) > 0

    # Properly quoted: preserves the full date
    text2 = 'name,deadline\nAbbrev,"Mar 15, 2027"\n'
    r2 = _csv(client, text2).json()
    assert r2["created"] == 1 and r2["errors"] == []
    items = client.get("/api/applications?type=scholarship").json()["items"]
    assert items[0]["deadline"] == "2027-03-15"


def test_csv_500_rows(client):
    """CSV with 500 rows should import without issues."""
    lines = ["name,amount,deadline"]
    for i in range(500):
        lines.append(f"Scholarship{i:03d},{100 + i},2027-01-01")
    text = "\n".join(lines) + "\n"
    r = _csv(client, text).json()
    assert r["created"] == 500 and r["errors"] == []
    count = client.get("/api/applications?type=scholarship").json()["count"]
    assert count == 500


def test_csv_header_only(client):
    """CSV with only header (no data rows) returns 0 created with no rows processed."""
    text = "name,amount,deadline\n"
    r = _csv(client, text).json()
    assert r["created"] == 0
    # The function silently returns with 0 created - it's not an error case
    # (errors list may be empty since there are no rows to process)


def test_csv_crlf_line_endings(client):
    """Excel-exported CSV with \\r\\n line endings should work."""
    text = "name,amount,deadline\r\nExcel,1000,2027-01-01\r\nTest,500,2027-02-01\r\n"
    r = _csv(client, text).json()
    assert r["created"] == 2 and r["errors"] == []


def test_csv_unicode_names(client):
    """Names with unicode characters should be preserved."""
    text = "name,org,amount\n李明,中国,1000\nАлексей,Россия,500\n"
    r = _csv(client, text).json()
    assert r["created"] == 2 and r["errors"] == []
    items = sorted(client.get("/api/applications?type=scholarship").json()["items"], key=lambda x: x["name"])
    # Check that both unicode names were preserved
    assert items[0]["name"] == "Алексей"
    assert items[1]["name"] == "李明"
    assert items[0]["org"] == "Россия"
    assert items[1]["org"] == "中国"


def test_csv_whitespace_trimming(client):
    """Whitespace in CSV cells should be trimmed."""
    text = "name,org,amount\n  Spaces  ,  Org  ,  1000  \n"
    r = _csv(client, text).json()
    assert r["created"] == 1 and r["errors"] == []
    items = client.get("/api/applications?type=scholarship").json()["items"]
    assert items[0]["name"] == "Spaces"
    assert items[0]["org"] == "Org"


def test_csv_case_insensitive_headers(client):
    """Headers should be case-insensitive (NAME vs name vs Name)."""
    text = "NAME,AMOUNT,Deadline\nCase Test,2000,2027-01-01\n"
    r = _csv(client, text).json()
    assert r["created"] == 1 and r["errors"] == []


def test_csv_empty_rows_ignored(client):
    """Empty rows (all blank cells) should be ignored."""
    text = "name,amount\nFirst,1000\n\n\nSecond,500\n"
    r = _csv(client, text).json()
    assert r["created"] == 2 and r["errors"] == []


def test_csv_missing_delimiter_in_row(client):
    """Row with fewer columns than header should use empty string for missing cells."""
    text = "name,amount,deadline\nIncomplete,1000\n"
    r = _csv(client, text).json()
    assert r["created"] == 1 and r["errors"] == []
    items = client.get("/api/applications?type=scholarship").json()["items"]
    assert items[0]["name"] == "Incomplete"
    assert items[0]["amount"] == 1000.0
    assert items[0]["deadline"] is None


def test_csv_extra_columns_ignored(client):
    """Extra columns beyond the header should be ignored."""
    text = "name,amount,extra1,extra2\nExtra,1000,ignored1,ignored2\n"
    r = _csv(client, text).json()
    assert r["created"] == 1 and r["errors"] == []


def test_csv_renewable_boolean_parsing(client):
    """Renewable field should parse yes/true/1/x correctly."""
    text = "name,renewable\nYes,yes\nTrue,true\nOne,1\nX,x\nNo,no\nEmpty,\n"
    r = _csv(client, text).json()
    assert r["created"] == 6 and r["errors"] == []
    items = {i["name"]: i["renewable"] for i in client.get("/api/applications?type=scholarship").json()["items"]}
    assert items["Yes"] is True
    assert items["True"] is True
    assert items["One"] is True
    assert items["X"] is True
    assert items["No"] is False
    assert items["Empty"] is False


def test_csv_duplicate_detection_ignores_case(client):
    """Duplicate detection should be case-insensitive."""
    _sch(client, name="Test", org="Org", deadline="2027-01-01")
    text = "name,org,deadline\ntest,ORG,2027-01-01\n"
    r = _csv(client, text).json()
    assert r["created"] == 0 and r["skipped_duplicates"] == 1


def test_csv_amounts_with_spaces(client):
    """Amounts with spaces like '1 500' should be handled."""
    text = "name,amount\nSpaced,1 500\n"
    r = _csv(client, text).json()
    assert r["created"] == 1 and r["errors"] == []
    items = client.get("/api/applications?type=scholarship").json()["items"]
    assert items[0]["amount"] == 1500.0


# ===== Scholarship Summary Edge Cases =====

def test_summary_scholarship_with_awarded_no_amount(client):
    """Scholarship with awarded_amount but no amount field should be counted in won."""
    s = _sch(client, name="Award Only", amount=None, status="decision", decision_result="accepted")
    client.patch(f"/api/applications/{s['id']}", json={"awarded_amount": 750})
    summary = client.get("/api/applications/scholarships/summary").json()
    assert summary["won_total"] == 750
    assert summary["won_count"] == 1
    # potential_total should not include scholarships with status=decision
    assert summary["potential_total"] == 0


def test_summary_multiple_won_amounts(client):
    """Sum of multiple awarded_amounts should be correct."""
    s1 = _sch(client, name="Award1", amount=1000, status="decision", decision_result="accepted")
    s2 = _sch(client, name="Award2", amount=2000, status="decision", decision_result="accepted")
    s3 = _sch(client, name="Award3", amount=500, status="decision", decision_result="accepted")
    client.patch(f"/api/applications/{s1['id']}", json={"awarded_amount": 500})
    client.patch(f"/api/applications/{s2['id']}", json={"awarded_amount": 1500})
    client.patch(f"/api/applications/{s3['id']}", json={"awarded_amount": 250})
    summary = client.get("/api/applications/scholarships/summary").json()
    assert summary["won_total"] == 2250
    assert summary["won_count"] == 3


def test_summary_archived_excluded_from_potential(client):
    """Archived scholarships should be excluded from potential_total."""
    s = _sch(client, name="Archived", amount=1000, deadline=_iso(10))
    client.patch(f"/api/applications/{s['id']}", json={"archived": True})
    s2 = _sch(client, name="Live", amount=2000, deadline=_iso(20))
    summary = client.get("/api/applications/scholarships/summary").json()
    assert summary["potential_total"] == 2000


def test_summary_archived_can_be_won(client):
    """Archived scholarships with awarded_amount should still count toward won_total."""
    s = _sch(client, name="Archived Won", amount=1000, status="decision", decision_result="accepted")
    client.patch(f"/api/applications/{s['id']}", json={"archived": True, "awarded_amount": 800})
    summary = client.get("/api/applications/scholarships/summary").json()
    # Note: Looking at the code, won is filtered from items (all scholarships)
    # not just live ones, so archived won should count
    assert summary["won_total"] == 800


def test_summary_decision_status_no_amount_in_potential(client):
    """Scholarships with status=decision should not be in potential_total."""
    s = _sch(client, name="Decision", amount=1000, status="decision", decision_result="accepted")
    s2 = _sch(client, name="Preparing", amount=2000, status="preparing", deadline=_iso(10))
    summary = client.get("/api/applications/scholarships/summary").json()
    # Only the "Preparing" one counts toward potential
    assert summary["potential_total"] == 2000


def test_summary_zero_amounts(client):
    """Scholarships with zero amount should be included in counts but not totals."""
    _sch(client, name="Zero1", amount=0, deadline=_iso(10))
    _sch(client, name="Zero2", amount=0, deadline=_iso(20))
    s = _sch(client, name="Regular", amount=1000, deadline=_iso(30))
    summary = client.get("/api/applications/scholarships/summary").json()
    assert summary["potential_total"] == 1000
    assert summary["count_by_status"]["researching"] == 3


def test_summary_large_amounts(client):
    """Large amounts should be summed correctly."""
    _sch(client, name="Large1", amount=1000000, deadline=_iso(10))
    _sch(client, name="Large2", amount=2000000, deadline=_iso(20))
    summary = client.get("/api/applications/scholarships/summary").json()
    assert summary["potential_total"] == 3000000.0


def test_summary_pending_count_excludes_decision(client):
    """pending_count should exclude scholarships with status=decision."""
    _sch(client, name="Research", status="researching", amount=1000)
    _sch(client, name="Preparing", status="preparing", amount=1000)
    _sch(client, name="Submitted", status="submitted", amount=1000)
    s = _sch(client, name="Decided", status="decision", decision_result="accepted", amount=1000)
    client.patch(f"/api/applications/{s['id']}", json={"awarded_amount": 800})
    summary = client.get("/api/applications/scholarships/summary").json()
    assert summary["pending_count"] == 3
    assert summary["won_count"] == 1


def test_summary_next_deadlines_excludes_archived_no_deadline(client):
    """next_deadlines should exclude archived and scholarships without deadlines."""
    s = _sch(client, name="Archived", amount=1000, deadline=_iso(5))
    client.patch(f"/api/applications/{s['id']}", json={"archived": True})
    _sch(client, name="No Deadline", amount=2000)
    _sch(client, name="Future", amount=3000, deadline=_iso(10))
    summary = client.get("/api/applications/scholarships/summary").json()
    assert len(summary["next_deadlines"]) == 1
    assert summary["next_deadlines"][0]["name"] == "Future"


def test_summary_next_deadlines_ordered_ascending(client):
    """next_deadlines should be ordered by deadline ascending."""
    _sch(client, name="First", amount=100, deadline=_iso(20))
    _sch(client, name="Second", amount=200, deadline=_iso(10))
    _sch(client, name="Third", amount=300, deadline=_iso(30))
    summary = client.get("/api/applications/scholarships/summary").json()
    names = [d["name"] for d in summary["next_deadlines"]]
    assert names == ["Second", "First", "Third"]


def test_summary_next_deadlines_capped_at_5(client):
    """next_deadlines should be capped at 5 items."""
    for i in range(10):
        _sch(client, name=f"Sch{i:02d}", amount=100, deadline=_iso(i + 1))
    summary = client.get("/api/applications/scholarships/summary").json()
    assert len(summary["next_deadlines"]) == 5
    # Should be the 5 earliest
    names = [d["name"] for d in summary["next_deadlines"]]
    assert names == [f"Sch{i:02d}" for i in range(5)]


def test_summary_invalid_deadline_ignored(client):
    """Scholarships with unparseable deadlines should be excluded from next_deadlines."""
    _sch(client, name="Valid", amount=100, deadline=_iso(10))
    # Manually create one with an invalid deadline (can't do via POST since it validates)
    from backend.services.applications import ApplicationsService
    from pathlib import Path

    svc = ApplicationsService(Path(client.app.dependency_overrides.get(None) or "/tmp"))
    # Actually, we need to use the test's data dir - get from the service
    svc = applications_router.get_service()
    s = svc.add(name="Invalid", type="scholarship", amount=100, deadline="not-a-date")

    summary = client.get("/api/applications/scholarships/summary").json()
    # Only the valid one should be in next_deadlines
    assert len(summary["next_deadlines"]) == 1
    assert summary["next_deadlines"][0]["name"] == "Valid"


def test_summary_past_deadlines_excluded(client):
    """Scholarships with past deadlines should be excluded from next_deadlines."""
    _sch(client, name="Past", amount=100, deadline=_iso(-5))
    _sch(client, name="Future", amount=200, deadline=_iso(10))
    summary = client.get("/api/applications/scholarships/summary").json()
    assert len(summary["next_deadlines"]) == 1
    assert summary["next_deadlines"][0]["name"] == "Future"


def test_summary_empty_list(client):
    """Summary on empty scholarship list should have zeros."""
    summary = client.get("/api/applications/scholarships/summary").json()
    assert summary["potential_total"] == 0
    assert summary["won_total"] == 0
    assert summary["won_count"] == 0
    assert summary["pending_count"] == 0
    assert summary["count_by_status"] == {}
    assert summary["next_deadlines"] == []
    assert summary["essays"] == []


def test_summary_awarded_without_decision_result(client):
    """Scholarship with awarded_amount but no decision_result=accepted should still count as won."""
    s = _sch(client, name="Award No Decision", amount=1000)
    client.patch(f"/api/applications/{s['id']}", json={"awarded_amount": 750})
    summary = client.get("/api/applications/scholarships/summary").json()
    # The logic is: won = [i for i in items if i.awarded_amount]
    # So it counts if awarded_amount is set, regardless of decision_result
    assert summary["won_total"] == 750
    assert summary["won_count"] == 1


def test_summary_non_scholarship_type_excluded(client):
    """Non-scholarship application types should be excluded from summary."""
    _sch(client, name="Scholarship", amount=1000, deadline=_iso(10))
    # Create a non-scholarship
    from fastapi.testclient import TestClient
    body = {"name": "Undergrad", "type": "undergrad", "amount": 5000, "deadline": _iso(10)}
    client.post("/api/applications", json=body)
    summary = client.get("/api/applications/scholarships/summary").json()
    # Should only count the scholarship, not the undergrad app
    assert summary["potential_total"] == 1000
    assert summary["pending_count"] == 1


def test_summary_count_by_status_only_scholarship_type(client):
    """count_by_status should only count scholarship-type applications."""
    _sch(client, name="Sch1", status="researching")
    _sch(client, name="Sch2", status="preparing")
    _sch(client, name="Sch3", status="researching")
    # Add a non-scholarship
    client.post("/api/applications", json={"name": "Undergrad", "type": "undergrad", "status": "researching"})
    summary = client.get("/api/applications/scholarships/summary").json()
    assert summary["count_by_status"] == {"researching": 2, "preparing": 1}


def test_csv_cp1252_decoded(client):
    raw = "name\nCaf\u00e9 Award\n".encode("cp1252")
    r = client.post("/api/applications/scholarships/import-csv", content=raw, headers={"content-type": "text/csv"})
    assert r.status_code == 200 and r.json()["created"] == 1
    items = client.get("/api/applications?type=scholarship").json()["items"]
    assert items[0]["name"] == "Caf\u00e9 Award"


def test_update_null_clears_amounts(client):
    item = client.post("/api/applications", json={"name": "S", "type": "scholarship", "awarded_amount": 500, "amount": 9}).json()
    iid = item.get("item", item)["id"]
    r = client.patch(f"/api/applications/{iid}", json={"awarded_amount": None, "amount": None})
    assert r.status_code == 200
    got = r.json()["item"]
    assert got["awarded_amount"] is None and got["amount"] is None
