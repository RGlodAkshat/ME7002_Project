#!/usr/bin/env bash
set -Eeuo pipefail
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"
./start-local.sh --install-only
exec "$PROJECT_DIR/backend/.venv/bin/python" "$PROJECT_DIR/infra/demo-runtime.py" "$@"
