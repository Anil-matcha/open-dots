#!/usr/bin/env bash
# Starts the whole stack for local development: Postgres (docker), migrations,
# the FastAPI app, the Telegram bot, and the web UI. Works under bash on
# Linux/macOS and Git Bash on Windows.
#
# Usage:
#   ./scripts/dev.sh                 # prepare configuration and start services
#   ./scripts/dev.sh --no-bot        # skip the Telegram bot
#   ./scripts/dev.sh --no-frontend   # skip the web UI
# Without BOAT_API_KEY, API and UI can start, but sandbox tasks need a key.

# An explicit `sh dev.sh` ignores the shebang. Re-enter Bash before using
# Bash-specific syntax (including on systems where /bin/sh is dash).
if [ -z "${BASH_VERSION:-}" ]; then
  exec bash "$0" "$@"
fi

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
FRONTEND_DIR="$ROOT_DIR/frontend"

RUN_BOT=1
BOT_SKIP_REASON="--no-bot"
RUN_FRONTEND=1
for arg in "$@"; do
  case "$arg" in
    --no-bot) RUN_BOT=0 ;;
    --no-frontend) RUN_FRONTEND=0 ;;
    --help|-h)
      echo "Usage: $0 [--no-bot] [--no-frontend]"
      echo "Creates local configuration and starts the API, optional bot, and web UI."
      exit 0
      ;;
    *)
      echo "Unknown option: $arg" >&2
      exit 1
      ;;
  esac
done

if [ "$RUN_FRONTEND" -eq 1 ] && [ ! -d "$FRONTEND_DIR" ]; then
  RUN_FRONTEND=0
fi

for tool in docker uv; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    echo "Missing required tool: $tool. Install it before starting development." >&2
    exit 1
  fi
done
if [ "$RUN_FRONTEND" -eq 1 ] && ! command -v npm >/dev/null 2>&1; then
  echo "Missing required tool: npm. Install Node.js or rerun with --no-frontend." >&2
  exit 1
fi
if ! docker compose version >/dev/null 2>&1; then
  echo "Docker Compose is unavailable. Install the Docker Compose plugin." >&2
  exit 1
fi
if ! docker info >/dev/null 2>&1; then
  echo "Docker is unavailable. Start Docker and check that your user can access it." >&2
  exit 1
fi

cd "$BACKEND_DIR"

if [ ! -f .env ]; then
  echo "==> Creating backend/.env from .env.example"
  (umask 077; cp .env.example .env)
fi

# uv supplies the project's Python and the dotenv/cryptography dependencies
# used to prepare configuration, so a separate system Python is unnecessary.
echo "==> Installing backend dependencies (uv sync)"
uv sync

echo "==> Preparing local development configuration"
# The helper prints only quoted export statements; .env contents are data.
env_exports="$(uv run --no-sync python "$SCRIPT_DIR/dev-env.py" "$BACKEND_DIR/.env")"
eval "$env_exports"
unset env_exports

if [ "$RUN_BOT" -eq 1 ] && [ -z "${TELEGRAM_BOT_TOKEN:-}" ]; then
  RUN_BOT=0
  BOT_SKIP_REASON="TELEGRAM_BOT_TOKEN is not set"
fi

if [ -z "${BOAT_API_KEY:-}" ]; then
  # Settings requires this field even when only using the API and web UI.
  export BOAT_API_KEY=""
  echo "==> BOAT_API_KEY is not set. API and web UI can start; sandbox tasks require a Boat API key in backend/.env."
fi

echo "==> Starting Postgres (docker compose)"
docker compose up -d

echo "==> Waiting for Postgres to be healthy"
POSTGRES_CONTAINER="$(docker compose ps -q postgres)"
if [ -z "$POSTGRES_CONTAINER" ]; then
  echo "Postgres container was not created by Docker Compose." >&2
  exit 1
fi
status="starting"
for _ in $(seq 1 30); do
  status="$(docker inspect --format='{{.State.Health.Status}}' "$POSTGRES_CONTAINER" 2>/dev/null || echo "starting")"
  [ "$status" = "healthy" ] && break
  [ "$status" = "unhealthy" ] && break
  sleep 1
done
if [ "$status" != "healthy" ]; then
  echo "Postgres did not become healthy in time." >&2
  exit 1
fi

echo "==> Running migrations (alembic upgrade head)"
uv run alembic upgrade head

pids=()
cleanup() {
  echo
  echo "==> Shutting down"
  for pid in "${pids[@]}"; do
    kill "$pid" 2>/dev/null || true
  done
}
trap cleanup EXIT INT TERM

echo "==> Starting FastAPI app on http://127.0.0.1:8000"
uv run fastapi dev app/main.py --host 127.0.0.1 --port 8000 &
pids+=("$!")

if [ "$RUN_BOT" -eq 1 ]; then
  echo "==> Starting Telegram bot"
  uv run python -m app.telegram_bot &
  pids+=("$!")
else
  echo "==> Skipping Telegram bot ($BOT_SKIP_REASON)"
fi

if [ "$RUN_FRONTEND" -eq 1 ]; then
  if [ ! -f "$FRONTEND_DIR/.env.local" ] && [ -f "$FRONTEND_DIR/.env.example" ]; then
    cp "$FRONTEND_DIR/.env.example" "$FRONTEND_DIR/.env.local"
  fi
  if [ ! -d "$FRONTEND_DIR/node_modules" ]; then
    echo "==> Installing frontend dependencies (npm install)"
    (cd "$FRONTEND_DIR" && npm install)
  fi
  echo "==> Starting web UI on http://127.0.0.1:3000"
  (cd "$FRONTEND_DIR" && npm run dev) &
  pids+=("$!")
else
  echo "==> Skipping web UI (--no-frontend)"
fi

echo "==> Everything is up. Press Ctrl+C to stop."
wait
