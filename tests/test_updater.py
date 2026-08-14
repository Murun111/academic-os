"""In-app self-updater (backend.services.updater / backend.routers.update).

Covers: eligibility in a dev-test process (never frozen -> eligible False),
the /install refusal path when ineligible, the codesign TeamIdentifier
verification gate, and network-failure classification on download. All
network calls (httpx) and subprocess calls (codesign/hdiutil) are
monkeypatched — no real GitHub calls, no real disk mounting.
"""
from __future__ import annotations

import subprocess
import sys

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.services import updater


# ── eligibility / status ────────────────────────────────────────────────


def test_eligibility_false_when_not_frozen(monkeypatch):
    """The test process is never a PyInstaller-frozen app, so eligibility
    must always be False regardless of platform — this is the guard that
    keeps the update button hidden in dev builds."""
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    elig = updater.eligibility()
    assert elig["eligible"] is False
    assert elig["reason"]


def test_status_reports_ineligible_in_tests(monkeypatch):
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    snap = updater.status()
    assert snap["eligible"] is False
    assert snap["eligible_reason"]
    assert snap["current_version"]
    assert snap["state"] == "idle"


@pytest.fixture
def client():
    from backend.app import app

    with TestClient(app) as c:
        yield c


def test_status_endpoint_eligible_false(client, monkeypatch):
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    r = client.get("/api/update/status")
    assert r.status_code == 200
    body = r.json()
    assert body["eligible"] is False
    assert body.get("eligible_reason")


# ── install refusal when ineligible ─────────────────────────────────────


def test_start_install_refuses_when_ineligible(monkeypatch):
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    # Make sure no stale running-state leaks in from another test.
    updater._set(state="idle", pct=None, error_kind=None, message=None)

    result = updater.start_install()
    assert result["ok"] is False
    assert result["error"] == "not_eligible"
    assert result["message"]


def test_install_endpoint_returns_friendly_refusal(client, monkeypatch):
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    updater._set(state="idle", pct=None, error_kind=None, message=None)

    r = client.post("/api/update/install")
    assert r.status_code == 400
    body = r.json()
    assert body["error_kind"] == "install_error"
    assert body["message"]


def test_install_endpoint_409_when_already_running(client, monkeypatch):
    """Distinct from the ineligible-refusal path: a job already running
    short-circuits before eligibility is even checked."""
    updater._set(state="downloading", pct=10.0, error_kind=None, message=None)
    try:
        r = client.post("/api/update/install")
        assert r.status_code == 409
        assert r.json()["error"] == "already_running"
    finally:
        updater._set(state="idle", pct=None, error_kind=None, message=None)


# ── codesign verification gate ──────────────────────────────────────────


def test_codesign_verify_rejects_mismatched_team_identifier(monkeypatch, tmp_path):
    """codesign --verify succeeds (return code 0) but the TeamIdentifier in
    `codesign -dvv` output doesn't match Academic OS's — must be treated as
    a verification failure, not silently accepted."""

    def fake_run(cmd, **kwargs):
        if cmd[0] == "codesign" and "--verify" in cmd:
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
        if cmd[0] == "codesign" and "-dvv" in cmd:
            return subprocess.CompletedProcess(
                cmd, 0, stdout="",
                stderr="Executable=/tmp/x\nIdentifier=com.evil.app\n"
                       "TeamIdentifier=DEADBEEF00\n",
            )
        raise AssertionError(f"unexpected subprocess call: {cmd}")

    monkeypatch.setattr(updater.subprocess, "run", fake_run)

    with pytest.raises(updater.UpdateError) as exc_info:
        updater._codesign_verify(tmp_path / "Academic OS.app")
    assert exc_info.value.kind == "verify_error"


def test_codesign_verify_accepts_matching_team_identifier(monkeypatch, tmp_path):
    def fake_run(cmd, **kwargs):
        if "--verify" in cmd:
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
        if "-dvv" in cmd:
            return subprocess.CompletedProcess(
                cmd, 0, stdout="",
                stderr=f"TeamIdentifier={updater.TEAM_IDENTIFIER}\n",
            )
        raise AssertionError(f"unexpected subprocess call: {cmd}")

    monkeypatch.setattr(updater.subprocess, "run", fake_run)

    # Should not raise.
    updater._codesign_verify(tmp_path / "Academic OS.app")


def test_codesign_verify_rejects_failed_verify_step(monkeypatch, tmp_path):
    """--verify --deep --strict itself fails (nonzero exit) — must raise
    before even looking at TeamIdentifier."""

    def fake_run(cmd, **kwargs):
        if "--verify" in cmd:
            return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="invalid signature")
        raise AssertionError("must not call -dvv after a failed --verify")

    monkeypatch.setattr(updater.subprocess, "run", fake_run)

    with pytest.raises(updater.UpdateError) as exc_info:
        updater._codesign_verify(tmp_path / "Academic OS.app")
    assert exc_info.value.kind == "verify_error"


# ── download failure classification ─────────────────────────────────────


def test_download_transport_error_is_network_error(monkeypatch, tmp_path):
    def fake_stream(method, url, **kwargs):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(updater.httpx, "stream", fake_stream)

    with pytest.raises(updater.UpdateError) as exc_info:
        updater._download("https://example.invalid/AcademicOS.dmg", tmp_path / "AcademicOS.dmg")
    assert exc_info.value.kind == "network_error"


def test_fetch_asset_url_transport_error_is_network_error(monkeypatch):
    def fake_get(url, **kwargs):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(updater.httpx, "get", fake_get)

    with pytest.raises(updater.UpdateError) as exc_info:
        updater._fetch_asset_url()
    assert exc_info.value.kind == "network_error"


def test_run_job_classifies_network_error_end_to_end(monkeypatch):
    """The background job (_run_job) must land the state machine in
    state=error/error_kind=network_error when GitHub is unreachable — this
    is what the status-polling UI actually reads."""

    def fake_get(url, **kwargs):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(updater.httpx, "get", fake_get)
    updater._set(state="checking", pct=None, error_kind=None, message=None,
                 available_version=None)

    updater._run_job()

    snap = updater._snapshot()
    assert snap["state"] == "error"
    assert snap["error_kind"] == "network_error"
    assert snap["message"]

    # Reset so this test can't bleed into others.
    updater._set(state="idle", pct=None, error_kind=None, message=None)


def test_install_rejects_cross_origin_browser_request(client):
    """CSRF guard: a browser-sent Origin outside the app's own origins must be
    refused before the updater even evaluates eligibility — a malicious
    webpage's form-POST to localhost is a CORS "simple request" that the CORS
    middleware alone would not block."""
    r = client.post("/api/update/install", headers={"Origin": "https://evil.example"})
    assert r.status_code == 403
    assert r.json()["error"] == "forbidden_origin"

    # Same-origin and origin-less callers still reach the normal handler
    # (400 friendly refusal here, since tests never run frozen).
    r2 = client.post("/api/update/install", headers={"Origin": "http://localhost:7878"})
    assert r2.status_code == 400


# ── _run_job full state-machine walk (happy path) ────────────────────────


def test_run_job_happy_path_reaches_restarting_and_relaunches_once(monkeypatch, tmp_path):
    """Every step mocked to succeed: _run_job walks the state machine to
    state=restarting and calls the _relaunch indirection exactly once.
    The relaunch indirection (updater._relaunch) is the module-level function
    that os_exit() calls through — monkeypatching it prevents the process
    from actually exiting while still verifying it fires."""
    relaunch_calls = []

    monkeypatch.setattr(updater, "_fetch_asset_url",
                        lambda: "https://example.com/AcademicOS.dmg")
    monkeypatch.setattr(updater, "_download", lambda url, dest: None)
    monkeypatch.setattr(updater, "_hdiutil_attach", lambda dmg: "/Volumes/FakeOS")
    monkeypatch.setattr(updater, "_locate_app",
                        lambda mp: tmp_path / "dmg" / updater.APP_BUNDLE_NAME)
    monkeypatch.setattr(updater, "_codesign_verify", lambda path: None)
    monkeypatch.setattr(updater, "_read_bundle_version", lambda path: "99.0.0")
    monkeypatch.setattr(updater, "_install", lambda path: None)
    monkeypatch.setattr(updater, "_relaunch", lambda: relaunch_calls.append(1))

    updater._set(state="checking", pct=None, error_kind=None, message=None,
                 available_version=None)
    updater._run_job()

    snap = updater._snapshot()
    assert snap["state"] == "restarting", (
        f"expected state=restarting, got {snap['state']!r}"
    )
    assert len(relaunch_calls) == 1, (
        f"expected _relaunch called once, got {len(relaunch_calls)}"
    )

    # Reset so this test can't bleed into others.
    updater._set(state="idle", pct=None, error_kind=None, message=None)


# ── _install rollback on copy failure ───────────────────────────────────


def test_install_failure_rolls_back_original_and_job_ends_in_error(monkeypatch, tmp_path):
    """ditto (the copy step inside _install) returns non-zero: the moved-aside
    original bundle is restored and _run_job lands in state=error /
    error_kind=install_error.

    _install is NOT mocked — the real move-aside + copy + rollback logic runs.
    Path("/Applications") is redirected to a tmp_path subdirectory so the test
    never touches /Applications and needs no elevated permissions.
    """
    import subprocess as _subprocess
    from pathlib import Path as _OrigPath

    # Fake /Applications with a pre-existing "Academic OS.app" to move aside.
    apps_dir = tmp_path / "Applications"
    apps_dir.mkdir()
    original_app = apps_dir / updater.APP_BUNDLE_NAME
    original_app.mkdir()
    marker = original_app / "original.txt"
    marker.write_text("original")

    # Source app on the (fake) mounted DMG.
    source_app = tmp_path / "dmg" / updater.APP_BUNDLE_NAME
    source_app.mkdir(parents=True)

    # Redirect Path("/Applications") → apps_dir; all other Path() calls are
    # passed through unchanged so _run_job's tempfile path and dmg_path work.
    def _patched_path(*args, **kwargs):
        if len(args) == 1 and str(args[0]) == "/Applications":
            return _OrigPath(str(apps_dir))
        return _OrigPath(*args, **kwargs)

    monkeypatch.setattr(updater, "Path", _patched_path)

    # Make subprocess.run fail for 'ditto' (the copy step); everything else
    # (hdiutil detach in the finally) succeeds — it's swallowed anyway.
    def fake_run(cmd, **kwargs):
        if cmd and cmd[0] == "ditto":
            return _subprocess.CompletedProcess(cmd, 1, stdout="", stderr="ditto: failed")
        return _subprocess.CompletedProcess(cmd if cmd else [], 0, stdout="", stderr="")

    monkeypatch.setattr(updater.subprocess, "run", fake_run)

    # All steps before _install are mocked to succeed.
    monkeypatch.setattr(updater, "_fetch_asset_url",
                        lambda: "https://example.com/AcademicOS.dmg")
    monkeypatch.setattr(updater, "_download", lambda url, dest: None)
    monkeypatch.setattr(updater, "_hdiutil_attach", lambda dmg: "/Volumes/FakeOS")
    monkeypatch.setattr(updater, "_locate_app", lambda mp: source_app)
    monkeypatch.setattr(updater, "_codesign_verify", lambda path: None)
    monkeypatch.setattr(updater, "_read_bundle_version", lambda path: "99.0.0")
    # _install is intentionally NOT mocked — the real rollback logic must run.

    updater._set(state="checking", pct=None, error_kind=None, message=None,
                 available_version=None)
    updater._run_job()

    snap = updater._snapshot()
    assert snap["state"] == "error", (
        f"expected state=error after install failure, got {snap['state']!r}"
    )
    assert snap["error_kind"] == "install_error", (
        f"expected error_kind=install_error, got {snap['error_kind']!r}"
    )

    # Rollback: original bundle must be back where it was.
    assert original_app.exists(), (
        "rollback failed: original app bundle was not restored after install failure"
    )
    assert marker.read_text() == "original", (
        "rollback restored the wrong directory (marker file content changed)"
    )
    # Backup must be gone (was renamed back to the original path).
    backup = apps_dir / (updater.APP_BUNDLE_NAME + ".bak")
    assert not backup.exists(), (
        "backup (.bak) should not exist after successful rollback"
    )

    # Reset so this test can't bleed into others.
    updater._set(state="idle", pct=None, error_kind=None, message=None)
