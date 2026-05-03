#!/usr/bin/env bash
set -euo pipefail

FUNCTIONS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$FUNCTIONS_DIR/.." && pwd)"

export REPO_ROOT
export PYTHONUNBUFFERED="${PYTHONUNBUFFERED:-1}"
export UDS="${UDS:-/tmp/native_rdma-dp.sock}"
export CTRL_URL="${CTRL_URL:-http://127.0.0.1:5000}"
export REQUIRE_PEER="${REQUIRE_PEER:-1}"
export ALLOW_DESTRUCTIVE="${ALLOW_DESTRUCTIVE:-0}"
export RUN_ALL_TS="${RUN_ALL_TS:-$(date +%Y%m%d_%H%M%S)}"

mkdir -p "$FUNCTIONS_DIR/logs"
STDIO_LOG="$FUNCTIONS_DIR/logs/run_all_${RUN_ALL_TS}.stdio.log"

set +e
python3 "$FUNCTIONS_DIR/run_all.py" "$@" 2>&1 | tee "$STDIO_LOG"
rc=${PIPESTATUS[0]}
set -e
exit "$rc"

