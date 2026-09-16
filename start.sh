#!/usr/bin/env bash
# Consilium one-command launcher.
# Sets up the venv, installs deps, detects a local Ollama, picks a free port,
# opens the app, and serves it WITHOUT --reload. (--reload restarts the process
# whenever the app persists its own state, which would kill the in-flight
# request -- so it is deliberately not used here.)
set -euo pipefail
cd "$(dirname "$0")"

PY="${PYTHON:-python3}"

# 1. virtualenv
if [ ! -d .venv ]; then
  echo "Creating virtualenv (.venv)…"
  "$PY" -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate

# 2. dependencies (idempotent)
echo "Installing dependencies…"
pip install -q --disable-pip-version-check -r backend/requirements.txt

# 3. model config: if there's no .env and a local Ollama is up, point at it
OLLAMA_HOST="${OLLAMA_HOST:-localhost:11434}"
if curl -sf "http://$OLLAMA_HOST/api/tags" >/dev/null 2>&1; then
  echo "✓ Ollama reachable at $OLLAMA_HOST"
  if [ ! -f .env ]; then
    cat > .env <<EOF
MODEL_PROVIDER=oss
MODEL_NAME=${OLLAMA_MODEL:-llama3.2}
BASE_URL=http://$OLLAMA_HOST/v1
API_KEY=not-needed-for-local
EOF
    echo "  Wrote .env → local Ollama (${OLLAMA_MODEL:-llama3.2}). Change the model any time in Settings."
  fi
else
  if command -v ollama >/dev/null 2>&1; then
    echo "⚠ Ollama is installed but not running at $OLLAMA_HOST."
    echo "  Start it in another terminal (or launch the Ollama app), then hit Save & test —"
    echo "  the app connects on your next save/refresh, no restart needed:"
    echo "      ollama serve"
    echo "      ollama pull ${OLLAMA_MODEL:-llama3.2}"
  else
    echo "⚠ Ollama not found — the app will run in deterministic fallback."
    echo "  For genuine reasoning: install Ollama (https://ollama.com), then 'ollama serve'"
    echo "  and 'ollama pull ${OLLAMA_MODEL:-llama3.2}'."
  fi
  echo "  (By design the app does NOT start Ollama for you — it's your model server to manage."
  echo "   Every decision still runs via the deterministic fallback in the meantime.)"
  [ -f .env ] || cp .env.example .env
fi

# 4. first free port from 8000 up
PORT="${PORT:-8000}"
while lsof -ti:"$PORT" >/dev/null 2>&1; do PORT=$((PORT + 1)); done
URL="http://localhost:$PORT"

# 5. open the browser shortly after boot (best-effort)
( sleep 2
  if command -v open >/dev/null 2>&1; then open "$URL"
  elif command -v xdg-open >/dev/null 2>&1; then xdg-open "$URL"
  fi ) >/dev/null 2>&1 &

echo "Consilium → $URL   (Ctrl-C to stop)"
exec uvicorn api.app:app --app-dir backend --host 127.0.0.1 --port "$PORT"
