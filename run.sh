#!/usr/bin/env bash
# Start the STAT 350 Tutor. Two modes, optional port:
#
#   ./run.sh serve [PORT]   production-like: build the SPA, then ONE uvicorn
#                           worker serves the built app + API. (default)
#   ./run.sh dev   [PORT]   hot-reload: uvicorn + Vite dev server (:5173, which
#                           proxies /api -> backend). Browse http://localhost:5173.
#
# Backend port (default 8100) — any of these; an argument overrides the env var:
#   ./run.sh serve 9000        ./run.sh serve --port 9000        PORT=9000 ./run.sh serve
#
# Env: GENAI_STUDIO_API_KEY for real answers (without it, degraded mode);
#      STAT350_VENV to override the venv (default ~/venvs/stat350-tutor).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Auto-load secrets from .env (repo root, gitignored) so you don't have to
# export them by hand. Copy .env.example -> .env and fill it in. A var already
# set in your shell wins (only unset ones are filled); values are NOT executed.
if [[ -f "$ROOT/.env" ]]; then
  while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line%$'\r'}"                          # tolerate Windows/WSL CRLF
    [[ "$line" =~ ^[[:space:]]*(#|$) ]] && continue
    [[ "$line" != *=* ]] && continue
    key="${line%%=*}"; val="${line#*=}"
    key="${key//[[:space:]]/}"
    val="${val#[\"\']}"; val="${val%[\"\']}"       # strip one layer of quotes
    [[ -z "${!key:-}" ]] && export "$key=$val"
  done < "$ROOT/.env"
fi

VENV="${STAT350_VENV:-$HOME/venvs/stat350-tutor}"
PY="$VENV/bin/python"
UVICORN="$VENV/bin/uvicorn"

MODE="serve"
PORT="${PORT:-8100}"
# Optional mode (dev|serve) and port (a bare number, or -p/--port N). An
# explicit port argument overrides the PORT env var.
while [[ $# -gt 0 ]]; do
  case "$1" in
    dev|serve)   MODE="$1"; shift ;;
    -p|--port)   PORT="${2:?run.sh: --port needs a value}"; shift 2 ;;
    -h|--help)   echo "usage: ./run.sh [dev|serve] [PORT] [--port PORT]"; exit 0 ;;
    ''|*[!0-9]*) echo "run.sh: unknown argument '$1'" >&2
                 echo "usage: ./run.sh [dev|serve] [PORT]" >&2; exit 2 ;;
    *)           PORT="$1"; shift ;;   # a bare number = the backend port
  esac
done
if ! [[ "$PORT" =~ ^[0-9]+$ ]] || [[ "$PORT" -lt 1 || "$PORT" -gt 65535 ]]; then
  echo "run.sh: invalid port '$PORT' (must be 1-65535)" >&2; exit 2
fi

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
    echo "usage: ./run.sh [dev|serve] [PORT]" >&2
    exit 2
    ;;
esac
