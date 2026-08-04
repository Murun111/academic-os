"""macOS native notification via osascript.

Best-effort: subprocess errors are swallowed; the function never raises.
Gated by env var NOTIFY (default "1"; "0" disables).  No-op on non-darwin.
"""
import os
import subprocess
import sys

_MAX_BODY = 200


def _escape(s: str) -> str:
    """Escape backslashes then double-quotes for an AppleScript string literal."""
    return s.replace("\\", "\\\\").replace('"', '\\"')


def notify(title: str, body: str, *, sound: bool = False) -> None:
    """Fire a macOS notification.  Never raises; swallows all exceptions."""
    if os.environ.get("NOTIFY", "1") == "0":
        return
    if sys.platform != "darwin":
        return
    try:
        body = body[:_MAX_BODY]
        script = f'display notification "{_escape(body)}" with title "{_escape(title)}"'
        if sound:
            script += ' sound name "Ping"'
        subprocess.run(["osascript", "-e", script], timeout=5, capture_output=True)
    except Exception:
        pass
