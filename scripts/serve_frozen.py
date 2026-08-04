"""Entry point for the frozen (PyInstaller) Academic OS server.

Serves the bundled webui and opens the browser once healthy. Data still
lives in ~/.academic-os — the app bundle is stateless and replaceable.
"""
from __future__ import annotations

import os
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

# In a PyInstaller onedir build, bundled data lives next to the executable
# under _internal/. backend/app.py resolves webui relative to its own file,
# which PyInstaller preserves, so no path surgery is needed — but we make
# the cwd sane and predictable.
if getattr(sys, "frozen", False):
    os.chdir(Path(sys.executable).parent)

PORT = int(os.environ.get("BIND_PORT", "7878"))
URL = f"http://127.0.0.1:{PORT}"


def _open_when_ready() -> None:
    deadline = time.time() + 30
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"{URL}/health", timeout=1) as r:
                if r.status == 200:
                    webbrowser.open(URL)
                    return
        except Exception:
            time.sleep(0.5)


def main() -> None:
    # If an instance is already running, just open the browser and exit.
    try:
        with urllib.request.urlopen(f"{URL}/health", timeout=1) as r:
            if r.status == 200:
                webbrowser.open(URL)
                return
    except Exception:
        pass

    threading.Thread(target=_open_when_ready, daemon=True).start()
    import uvicorn
    from backend.app import app
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")


if __name__ == "__main__":
    main()
