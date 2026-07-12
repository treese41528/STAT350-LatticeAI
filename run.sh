#!/usr/bin/env bash
# Start the STAT 350 Tutor. Two modes:
#
#   ./run.sh dev     hot-reload: uvicorn (:8100) + Vite dev server (:5173, proxies
#                    /api -> :8100). Browse http://localhost:5173. Ctrl-C stops both.
#   ./run.sh serve   production-like: build the SPA, then ONE uvicorn worker serves
#                    the built app + API at http://localhost:8100. (default)
#
# Env: GENAI_STUDIO_API_KEY for real answers (without it, degraded mode);
#      STAT350_VENV to override the venv (default ~/venvs/stat350-tutor);
#      PORT to override the backend port (default 8100).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODE="${1:-serve}"
PORT="${PORT:-8100}"
VENV="${STAT350_VENV:-$HOME/venvs/stat350-tutor}"
PY="$VENV/bin/python"
UVICORN="$VENV/bin/uvicorn"

if [[ ! -x "$PY" ]]; then
  echo "No venv at $VENV. Create it (see TESTING.md §0) or set STAT350_VENV." >&2
  exit 1
fi
if [[ -z "${GENAI_STUDIO_API_KEY:-}" ]]; then
  echo "⚠️  GENAI_STUDIO_API_KEY not set — running in DEGRADED mode (deterministic"
  echo "   answers only; concept/syllabus questions return 'gateway unavailable')."
fi

case "$MODE" in
  serve)
    echo "→ Building the frontend…"
    ( cd "$ROOT/frontend" && npm run build )
    echo "→ Serving at http://localhost:$PORT (one worker; SPA + API)"
    exec "$UVICORN" app.main:app --app-dir "$ROOT/backend" \
         --host 127.0.0.1 --port "$PORT" --workers 1
    ;;
  dev)
    echo "→ Backend (reload) on :$PORT"
    ( cd "$ROOT/backend" && exec "$UVICORN" app.main:app \
        --host 127.0.0.1 --port "$PORT" --reload ) &
    BACK=$!
    trap 'echo; echo "stopping…"; kill "$BACK" 2>/dev/null || true' INT TERM EXIT
    echo "→ Frontend dev server on :5173 (proxies /api -> :$PORT)"
    ( cd "$ROOT/frontend" && VITE_API_TARGET="http://localhost:$PORT" npm run dev:backend )
    ;;
  *)
    echo "usage: ./run.sh [dev|serve]" >&2
    exit 2
    ;;
esac
