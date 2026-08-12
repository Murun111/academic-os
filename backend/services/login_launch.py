"""Start-at-login (macOS LaunchAgent).

Deadlines don't wait for the app to be opened — this writes a per-user
LaunchAgent so the Academic OS server starts at login, which makes the
daily deadline notification and Canvas auto-sync work "while closed".

Packaged app: launches the frozen binary. Dev checkout: launches uvicorn
from the repo venv. No admin rights involved; disable removes the file.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

LABEL = "org.academicos.autostart"


def _plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def _program_args() -> list[str] | None:
    if sys.platform != "darwin":
        return None
    if getattr(sys, "frozen", False):
        return [sys.executable]
    # dev checkout: repo root is two levels up from this file
    repo = Path(__file__).resolve().parent.parent.parent
    uvicorn = repo / ".venv" / "bin" / "uvicorn"
    if not uvicorn.exists():
        return None
    return [str(uvicorn), "backend.app:app", "--port", os.environ.get("BIND_PORT", "7878")]


def enabled() -> bool:
    return _plist_path().exists()


def enable() -> dict:
    if sys.platform != "darwin":
        return {"error": "start-at-login is only available on macOS"}
    args = _program_args()
    if not args:
        return {"error": "could not determine how to launch the app"}
    repo = Path(__file__).resolve().parent.parent.parent
    args_xml = "\n".join(f"        <string>{a}</string>" for a in args)
    plist = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>{LABEL}</string>
    <key>ProgramArguments</key>
    <array>
{args_xml}
    </array>
    <key>WorkingDirectory</key><string>{repo}</string>
    <key>RunAtLoad</key><true/>
    <key>KeepAlive</key><false/>
</dict>
</plist>
"""
    p = _plist_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(plist)
    try:
        subprocess.run(["launchctl", "load", "-w", str(p)], capture_output=True, timeout=10)
    except (subprocess.SubprocessError, OSError):
        pass  # the plist still takes effect at next login
    return {"ok": True, "enabled": True}


def disable() -> dict:
    p = _plist_path()
    try:
        subprocess.run(["launchctl", "unload", "-w", str(p)], capture_output=True, timeout=10)
    except (subprocess.SubprocessError, OSError):
        pass
    p.unlink(missing_ok=True)
    return {"ok": True, "enabled": False}
