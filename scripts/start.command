#!/bin/bash
# Academic OS launcher — double-click to start.
# First run sets everything up; afterwards it just boots and opens the browser.
# Close this window to stop the app. Your data lives in ~/.academic-os and is
# never touched by updates or reinstalls.
set -e
cd "$(dirname "$0")/.."

PORT="${BIND_PORT:-7878}"
URL="http://127.0.0.1:$PORT"

echo "── Academic OS ──────────────────────────────"

# Already running? Just open the browser.
health_response=$(curl -s --max-time 2 "$URL/health" 2>/dev/null || true)

if echo "$health_response" | grep -q '"ok"'; then
  # Health endpoint responds — verify the uvicorn process is actually running.
  if pgrep -f "uvicorn backend.app:app" >/dev/null; then
    echo "Already running — opening $URL"
    open "$URL"
    exit 0
  else
    # Port is responding but no uvicorn process exists: another app owns the port.
    echo "⚠ Port $PORT is responding, but the Academic OS server isn't running."
    echo "Another program owns this port. Try quitting it and run this again."
    read -r -p "Press Enter to close."
    exit 1
  fi
elif [ -n "$health_response" ]; then
  # Port is open but responds with something other than {"ok"}.
  echo "Port $PORT is in use by another app — quit it and try again."
  read -r -p "Press Enter to close."
  exit 1
fi

# First-run: create the Python environment.
if [ ! -x ".venv/bin/uvicorn" ]; then
  echo "First run: setting up (2-3 minutes, one time only)…"
  PY="$(command -v python3 || true)"
  if [ -z "$PY" ]; then
    echo "Python 3 is required but not found."
    echo "Install it from https://www.python.org/downloads/ and run this again."
    read -r -p "Press Enter to close."
    exit 1
  fi
  "$PY" -m venv .venv
  ./.venv/bin/pip install -q --upgrade pip
  ./.venv/bin/pip install -q -r requirements.txt
  echo "Environment ready."
fi

# The web interface must be built (ships pre-built; rebuild only if missing).
if [ ! -f "webui/dist/index.html" ]; then
  if command -v npm >/dev/null 2>&1; then
    echo "Building the interface (one time)…"
    (cd webui && npm install --no-audit --no-fund >/dev/null && npm run build >/dev/null)
  else
    echo "The web interface isn't built and npm isn't installed."
    echo "Ask whoever gave you this to run: cd webui && npm install && npm run build"
    read -r -p "Press Enter to close."
    exit 1
  fi
fi

# Optional AI: note the state, never block on it.
if curl -s --max-time 2 "http://localhost:11434/api/tags" >/dev/null 2>&1; then
  echo "Local AI: connected (Ollama)"
else
  echo "Local AI: off — the app fully works without it."
  echo "  (To enable essay feedback later: install Ollama from https://ollama.com)"
fi

echo "Starting… your browser will open at $URL"
echo "Keep this window open while you use the app. Close it to quit."
echo "─────────────────────────────────────────────"

# Open the browser once the server is up, then run the server in the
# foreground so closing the Terminal window stops it cleanly.
( for _ in $(seq 1 40); do
    sleep 0.5
    if curl -s --max-time 1 "$URL/health" | grep -q '"ok"'; then open "$URL"; exit 0; fi
  done ) &

exec ./.venv/bin/uvicorn backend.app:app --host 127.0.0.1 --port "$PORT" --log-level warning
