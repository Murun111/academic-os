"""In-app self-updater (macOS only).

Async job pattern like local_llm's start_running_async: POST /install kicks
off a background thread and returns immediately; GET /status reports the
job's progress. States: idle / checking / downloading (with pct) /
verifying / installing / restarting / error(error_kind, message).

Flow: fetch the latest GitHub release → pick the AcademicOS.dmg asset →
download it with progress → hdiutil attach → locate "Academic OS.app" on
the mounted volume → codesign --verify --deep --strict + confirm
TeamIdentifier == 4ULN66CM6Q → read the *verified* app's own
CFBundleShortVersionString and compare it to APP_VERSION (never trust the
GitHub tag name for that decision — only the signed bundle) → ditto over
/Applications/Academic OS.app (existing app is moved aside first and
restored on failure, never just deleted) → hdiutil detach → relaunch.

Never touches ~/.academic-os — only the app bundle at /Applications is
replaced.
"""
from __future__ import annotations

import plistlib
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import httpx

from backend.version import APP_VERSION, UPDATE_REPO

TEAM_IDENTIFIER = "4ULN66CM6Q"
ASSET_NAME = "AcademicOS.dmg"
APP_BUNDLE_NAME = "Academic OS.app"
GITHUB_TIMEOUT = 20
DOWNLOAD_TIMEOUT = 120

RUNNING_STATES = {"checking", "downloading", "verifying", "installing", "restarting"}


class UpdateError(Exception):
    """Raised at any job step; kind is one of network_error/verify_error/install_error."""

    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind
        self.message = message


_lock = threading.Lock()
_thread: threading.Thread | None = None
_state: dict = {
    "state": "idle",
    "pct": None,
    "error_kind": None,
    "message": None,
    "available_version": None,
}


def _set(**kw) -> None:
    with _lock:
        _state.update(kw)


def _snapshot() -> dict:
    with _lock:
        return dict(_state)


# ── eligibility ──────────────────────────────────────────────────

def _app_bundle_path() -> Path | None:
    """The running .app's own bundle path, or None outside a frozen app."""
    if not getattr(sys, "frozen", False):
        return None
    exe = Path(sys.executable).resolve()
    for parent in exe.parents:
        if parent.suffix == ".app":
            return parent
    return None


def eligibility() -> dict:
    """darwin + frozen + installed under /Applications — install refuses
    otherwise, and the UI hides the update button when not eligible."""
    if sys.platform != "darwin":
        return {"eligible": False, "reason": "Updates are only available on macOS."}
    if not getattr(sys, "frozen", False):
        return {"eligible": False, "reason": "Self-update isn't available in a dev build."}
    app_path = _app_bundle_path()
    if app_path is None:
        return {"eligible": False, "reason": "Couldn't locate the app bundle."}
    if app_path.parent != Path("/Applications"):
        return {"eligible": False, "reason": "Move Academic OS to /Applications to enable self-update."}
    return {"eligible": True, "reason": None}


# ── status ───────────────────────────────────────────────────────

def status() -> dict:
    elig = eligibility()
    snap = _snapshot()
    return {
        **snap,
        "current_version": APP_VERSION,
        "repo": UPDATE_REPO,
        "eligible": elig["eligible"],
        "eligible_reason": elig["reason"],
    }


# ── version comparison (only ever run against a codesign-verified bundle) ──

def _version_gt(a: str, b: str) -> bool:
    def parts(v: str) -> tuple[int, ...] | None:
        try:
            return tuple(int(x) for x in v.strip().split("."))
        except ValueError:
            return None

    pa, pb = parts(a), parts(b)
    if pa is not None and pb is not None:
        return pa > pb
    return a != b and a > b  # weak lexicographic fallback


# ── job ──────────────────────────────────────────────────────────

def start_install() -> dict:
    """Atomically start the update job. Returns {"ok": False, "error":
    "already_running"} or {"ok": False, "error": "not_eligible", "message":
    ...} without touching anything, or {"ok": True, "starting": True}."""
    global _thread
    with _lock:
        if _state["state"] in RUNNING_STATES:
            return {"ok": False, "error": "already_running"}
        elig = eligibility()
        if not elig["eligible"]:
            return {"ok": False, "error": "not_eligible", "message": elig["reason"]}
        _state.update(state="checking", pct=None, error_kind=None, message=None)
        _thread = threading.Thread(target=_run_job, daemon=True)
        _thread.start()
    return {"ok": True, "starting": True}


def _run_job() -> None:
    mount_point: str | None = None
    dmg_path: Path | None = None
    tmp_dir: str | None = None
    try:
        tmp_dir = tempfile.mkdtemp(prefix="academic-os-update-")

        # 1. fetch latest release, pick the dmg asset
        asset_url = _fetch_asset_url()

        # 2. download with progress
        _set(state="downloading", pct=0.0)
        dmg_path = Path(tmp_dir) / ASSET_NAME
        _download(asset_url, dmg_path)

        # 3. mount, locate the app, verify signature + team, compare version
        _set(state="verifying", pct=None)
        mount_point = _hdiutil_attach(dmg_path)
        app_in_dmg = _locate_app(mount_point)
        _codesign_verify(app_in_dmg)
        new_version = _read_bundle_version(app_in_dmg)

        if not _version_gt(new_version, APP_VERSION):
            _set(state="idle", pct=None, error_kind=None,
                 message="You're already on the latest version.",
                 available_version=new_version)
            return

        _set(available_version=new_version)

        # 4. install over /Applications (existing app moved aside, not deleted)
        _set(state="installing", pct=None)
        _install(app_in_dmg)

        # 5. relaunch
        _set(state="restarting", pct=None)
        _relaunch()
    except UpdateError as e:
        _set(state="error", pct=None, error_kind=e.kind, message=e.message)
    except Exception as e:  # noqa: BLE001 — the job must never crash the app
        kind = "network_error" if isinstance(e, (httpx.TransportError, httpx.HTTPStatusError)) else "install_error"
        _set(state="error", pct=None, error_kind=kind,
             message=f"{type(e).__name__}: {e}")
    finally:
        if mount_point:
            try:
                subprocess.run(["hdiutil", "detach", mount_point, "-quiet"],
                                capture_output=True, timeout=30)
            except Exception:
                pass
        if tmp_dir:
            shutil.rmtree(tmp_dir, ignore_errors=True)


def _fetch_asset_url() -> str:
    url = f"https://api.github.com/repos/{UPDATE_REPO}/releases/latest"
    try:
        r = httpx.get(url, timeout=GITHUB_TIMEOUT, headers={"Accept": "application/vnd.github+json"})
        r.raise_for_status()
        release = r.json()
    except httpx.TransportError as e:
        raise UpdateError("network_error", "Couldn't reach GitHub to check for updates.") from e
    except httpx.HTTPStatusError as e:
        raise UpdateError("network_error", f"GitHub returned an error (HTTP {e.response.status_code}).") from e

    for asset in release.get("assets") or []:
        if asset.get("name") == ASSET_NAME:
            download_url = asset.get("browser_download_url")
            if download_url:
                if not download_url.startswith("https://"):
                    raise UpdateError(
                        "network_error",
                        "The update asset URL was not https and was refused.",
                    )
                return download_url
    raise UpdateError("network_error", "No installer found in the latest release.")


_MAX_DOWNLOAD_REDIRECTS = 5


def _download(url: str, dest: Path) -> None:
    # follow_redirects=True would let an initial https:// URL hop to plain
    # http:// mid-download with no further check — httpx only exposes the
    # final scheme after the fact. Instead, follow redirects manually
    # (client default is follow_redirects=False) so every hop's scheme is
    # checked BEFORE it's requested.
    try:
        with httpx.Client(timeout=DOWNLOAD_TIMEOUT) as client:
            current_url = url
            for _ in range(_MAX_DOWNLOAD_REDIRECTS + 1):
                if not current_url.startswith("https://"):
                    raise UpdateError(
                        "network_error",
                        "The update download URL is not secure (https required).",
                    )
                with client.stream("GET", current_url) as r:
                    if 300 <= r.status_code < 400 and "location" in r.headers:
                        current_url = str(r.url.join(r.headers["location"]))
                        continue
                    r.raise_for_status()
                    total = int(r.headers.get("content-length") or 0)
                    got = 0
                    with open(dest, "wb") as f:
                        for chunk in r.iter_bytes(1024 * 512):
                            f.write(chunk)
                            got += len(chunk)
                            if total:
                                _set(pct=round(got / total * 100, 1))
                    return
            raise UpdateError("network_error", "Too many redirects while downloading the update.")
    except httpx.TransportError as e:
        raise UpdateError("network_error", "The update download was interrupted.") from e
    except httpx.HTTPStatusError as e:
        raise UpdateError("network_error", f"Couldn't download the update (HTTP {e.response.status_code}).") from e


def _hdiutil_attach(dmg_path: Path) -> str:
    proc = subprocess.run(
        ["hdiutil", "attach", "-nobrowse", "-readonly", "-plist", str(dmg_path)],
        capture_output=True, timeout=60,
    )
    if proc.returncode != 0:
        raise UpdateError("install_error", "Couldn't mount the downloaded update.")
    try:
        plist = plistlib.loads(proc.stdout)
    except Exception as e:
        raise UpdateError("install_error", "Couldn't read the mounted update volume.") from e
    for entity in plist.get("system-entities") or []:
        mp = entity.get("mount-point")
        if mp:
            return mp
    raise UpdateError("install_error", "Couldn't find the mounted update volume.")


def _locate_app(mount_point: str) -> Path:
    """Only ever return a path that resolves to somewhere under the mounted
    DMG — a symlink inside the volume (e.g. named "Academic OS.app" or
    matching *.app) could otherwise point outside it before codesign/ditto
    ever look at it."""
    mount_root = Path(mount_point).resolve()

    def _confined(path: Path) -> bool:
        try:
            return path.resolve().is_relative_to(mount_root)
        except OSError:
            return False

    candidate = mount_root / APP_BUNDLE_NAME
    if candidate.is_dir() and _confined(candidate):
        return candidate
    for found in mount_root.glob("*.app"):
        if _confined(found):
            return found
    raise UpdateError("install_error", "Couldn't find Academic OS.app in the update image.")


def _codesign_verify(app_path: Path) -> None:
    proc = subprocess.run(
        ["codesign", "--verify", "--deep", "--strict", str(app_path)],
        capture_output=True, text=True, timeout=60,
    )
    if proc.returncode != 0:
        raise UpdateError("verify_error", "The downloaded update failed a security check and was not installed.")

    proc2 = subprocess.run(
        ["codesign", "-dvv", str(app_path)],
        capture_output=True, text=True, timeout=60,
    )
    team_id = None
    for line in proc2.stderr.splitlines():
        if line.startswith("TeamIdentifier="):
            team_id = line.split("=", 1)[1].strip()
            break
    if team_id != TEAM_IDENTIFIER:
        raise UpdateError("verify_error", "The downloaded update's signature doesn't match Academic OS and was not installed.")


def _read_bundle_version(app_path: Path) -> str:
    info_plist = app_path / "Contents" / "Info.plist"
    try:
        with open(info_plist, "rb") as f:
            plist = plistlib.load(f)
    except Exception as e:
        raise UpdateError("verify_error", "Couldn't read the update's version.") from e
    version = plist.get("CFBundleShortVersionString")
    if not version:
        raise UpdateError("verify_error", "Couldn't read the update's version.")
    return version


def _install(app_in_dmg: Path) -> None:
    target = Path("/Applications") / APP_BUNDLE_NAME
    backup = target.parent / f"{target.name}.bak"

    if backup.exists():
        shutil.rmtree(backup, ignore_errors=True)
    moved_aside = False
    if target.exists():
        target.rename(backup)
        moved_aside = True

    try:
        proc = subprocess.run(
            ["ditto", str(app_in_dmg), str(target)],
            capture_output=True, text=True, timeout=120,
        )
        if proc.returncode != 0:
            raise UpdateError("install_error", "Couldn't install the update. Nothing was changed.")
        # Re-verify the INSTALLED copy before we ever relaunch it: /Applications
        # is writable by this (non-root) user, so any local process could swap
        # the bundle in the window after ditto — and a locally-written bundle
        # gets no Gatekeeper check at launch. Verify-what-you-run, not just
        # verify-what-you-copied.
        _codesign_verify(target)
    except Exception as install_exc:
        # Restore the previous app so the machine is never left without one —
        # but the rollback itself (rmtree + rename) can fail too (cross-device
        # rename, permissions, a backup partially removed by a race), so it
        # gets its own guard. Without this, a rollback failure would escape
        # this handler and, worse, get reported as "Nothing was changed" —
        # which would be a lie: target may now not exist at all.
        try:
            if target.exists():
                shutil.rmtree(target, ignore_errors=True)
            if moved_aside and backup.exists():
                backup.rename(target)
        except Exception as rollback_exc:
            raise UpdateError(
                "install_error",
                "The update failed and restoring the previous version also failed "
                f"({type(rollback_exc).__name__}: {rollback_exc}). "
                f"The previous app may still be recoverable at {backup} — "
                "restore it manually before relying on Academic OS again.",
            ) from rollback_exc
        if isinstance(install_exc, UpdateError):
            raise
        raise UpdateError("install_error", "Couldn't install the update. Nothing was changed.") from install_exc
    else:
        if moved_aside and backup.exists():
            shutil.rmtree(backup, ignore_errors=True)


def _relaunch() -> None:
    # Stop the bundled llama-server first: os._exit() kills only this process,
    # and an orphaned child would reparent to launchd and hold its port + RAM
    # through every future update cycle. Best-effort — never blocks relaunch.
    try:
        from backend.services import local_llm
        local_llm.stop()
    except Exception:
        pass
    target = Path("/Applications") / APP_BUNDLE_NAME
    subprocess.Popen(
        ["/bin/bash", "-c", f'sleep 1 && open -n "{target}"'],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    # Exit well before the relaunch's own "already running?" health check
    # fires (~1s), so it doesn't just open a browser tab against a server
    # that's about to disappear — it needs to find nothing running and
    # boot its own uvicorn instance.
    threading.Timer(0.3, lambda: os_exit()).start()


def os_exit() -> None:  # indirection so tests can monkeypatch the hard exit
    import os
    os._exit(0)
