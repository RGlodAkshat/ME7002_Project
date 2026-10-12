#!/usr/bin/env bash

set -Eeuo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$PROJECT_DIR/backend"
FRONTEND_DIR="$PROJECT_DIR/frontend"
RUN_DIR="$PROJECT_DIR/.run"
FRONTEND_PORT="${FRONTEND_PORT:-8082}"
API_PORT="${API_PORT:-8083}"
GATEWAY_PORT="${GATEWAY_PORT:-9002}"
PIDS=()

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1"
    echo "$2"
    exit 1
  fi
}

port_is_busy() {
  command -v lsof >/dev/null 2>&1 && lsof -nP -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1
}

cleanup() {
  trap - EXIT INT TERM
  if ((${#PIDS[@]})); then
    echo
    echo "Stopping manufacturing platform services..."
    kill "${PIDS[@]}" 2>/dev/null || true
    wait "${PIDS[@]}" 2>/dev/null || true
  fi
}

show_logs() {
  for log in "$RUN_DIR"/*.log; do
    [[ -f "$log" ]] || continue
    echo "--- $(basename "$log") ---"
    tail -n 30 "$log"
  done
}

wait_for_url() {
  local name="$1"
  local url="$2"
  local attempts=60
  while ((attempts > 0)); do
    if curl --silent --fail --max-time 1 "$url" >/dev/null 2>&1; then
      return 0
    fi
    attempts=$((attempts - 1))
    sleep 0.5
  done
  echo "$name did not become ready at $url"
  show_logs
  exit 1
}

trap cleanup EXIT INT TERM

require_command python3 "Install Python 3.12 or newer from https://www.python.org/downloads/"
require_command node "Install Node.js 20 or newer from https://nodejs.org/"
require_command npm "npm is included with Node.js."
require_command curl "curl is required for local health checks."

mkdir -p "$RUN_DIR"

echo "Installing backend dependencies..."
if [[ ! -x "$BACKEND_DIR/.venv/bin/python" ]]; then
  python3 -m venv "$BACKEND_DIR/.venv"
fi
"$BACKEND_DIR/.venv/bin/python" -m ensurepip --upgrade >/dev/null
"$BACKEND_DIR/.venv/bin/python" -m pip install --disable-pip-version-check -q -r "$BACKEND_DIR/requirements.txt"

if [[ ! -f "$BACKEND_DIR/.env" ]]; then
  cp "$BACKEND_DIR/.env.example" "$BACKEND_DIR/.env"
fi
python3 "$PROJECT_DIR/infra/prepare-secrets.py" "$BACKEND_DIR/.env"

echo "Installing frontend dependencies..."
(cd "$FRONTEND_DIR" && npm ci)

if [[ "${1:-}" == "--install-only" ]]; then
  echo "Dependencies installed successfully."
  exit 0
fi

for port in "$FRONTEND_PORT" "$API_PORT" "$GATEWAY_PORT"; do
  if port_is_busy "$port"; then
    echo "Port $port is already in use. Stop that process and run this script again."
    lsof -nP -iTCP:"$port" -sTCP:LISTEN || true
    exit 1
  fi
done

: >"$RUN_DIR/gateway.log"
: >"$RUN_DIR/backend.log"
: >"$RUN_DIR/frontend.log"

echo "Starting machine gateway simulator on port $GATEWAY_PORT..."
(
  cd "$PROJECT_DIR"
  PORT="$GATEWAY_PORT" \
  PLATFORM_ENV_FILE="$BACKEND_DIR/.env" \
  PLATFORM_CALLBACK_URL="http://127.0.0.1:$API_PORT/api/machine/events" \
  python3 infra/machine-simulator/server.py
) >"$RUN_DIR/gateway.log" 2>&1 &
PIDS+=("$!")

echo "Starting backend API on port $API_PORT..."
(
  cd "$BACKEND_DIR"
  DATABASE_URL="${DATABASE_URL:-sqlite:///./manufacturing_platform.db}" \
  CORS_ORIGINS="http://localhost:$FRONTEND_PORT,http://127.0.0.1:$FRONTEND_PORT" \
  MACHINE_CALLBACK_URL="http://127.0.0.1:$API_PORT/api/machine/events" \
  "$BACKEND_DIR/.venv/bin/python" -m uvicorn app.main:app --host 0.0.0.0 --port "$API_PORT"
) >"$RUN_DIR/backend.log" 2>&1 &
PIDS+=("$!")

echo "Starting website on port $FRONTEND_PORT..."
(
  cd "$FRONTEND_DIR"
  API_PROXY_TARGET="http://127.0.0.1:$API_PORT" npm run dev -- --host 0.0.0.0 --port "$FRONTEND_PORT" --strictPort
) >"$RUN_DIR/frontend.log" 2>&1 &
PIDS+=("$!")

wait_for_url "Gateway" "http://127.0.0.1:$GATEWAY_PORT/health"
wait_for_url "Backend" "http://127.0.0.1:$API_PORT/health"
wait_for_url "Frontend" "http://127.0.0.1:$FRONTEND_PORT"

echo
echo "Manufacturing platform is running."
echo "Website:     http://localhost:$FRONTEND_PORT"
echo "API docs:    http://localhost:$API_PORT/docs"
echo "Gateway:     http://localhost:$GATEWAY_PORT/health"
echo "Logs:        $RUN_DIR"
echo "Open the website to create the first administrator and import a manufacturing configuration."
echo
echo "Press Ctrl+C to stop all services."

while true; do
  for pid in "${PIDS[@]}"; do
    if ! kill -0 "$pid" 2>/dev/null; then
      echo "A service stopped unexpectedly."
      show_logs
      exit 1
    fi
  done
  sleep 2
done
