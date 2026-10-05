#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"
PYTHON_BIN="${PYTHON_BIN:-python3}"
export HOST="${HOST:-127.0.0.1}"
export PORT="${PORT:-5000}"
export WAITRESS_THREADS="${WAITRESS_THREADS:-8}"

exec "$PYTHON_BIN" "$ROOT/serve.py"
