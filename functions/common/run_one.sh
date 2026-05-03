#!/usr/bin/env bash
set -euo pipefail

FN_DIR="${1:?missing FN_DIR}"
shift || true

FN_DIR="$(cd "$FN_DIR" && pwd)"
MODULE_DIR="$(cd "$FN_DIR/.." && pwd)"
FUNCTIONS_DIR="$(cd "$MODULE_DIR/.." && pwd)"
REPO_ROOT="$(cd "$FUNCTIONS_DIR/.." && pwd)"

export REPO_ROOT
export OUT_DIR="${OUT_DIR:-$FN_DIR}"
export LOG_DIR="${LOG_DIR:-$FN_DIR/logs}"
export UDS="${UDS:-/tmp/native_rdma-dp.sock}"
export CTRL_URL="${CTRL_URL:-http://127.0.0.1:5000}"
export REQUIRE_PEER="${REQUIRE_PEER:-1}"
export ALLOW_DESTRUCTIVE="${ALLOW_DESTRUCTIVE:-0}"
export PYTHONUNBUFFERED="${PYTHONUNBUFFERED:-1}"
export PYTHONPATH="$FUNCTIONS_DIR:${PYTHONPATH:-}"
export RUN_TS="${RUN_TS:-$(date +%Y%m%d_%H%M%S)}"

mkdir -p "$LOG_DIR"
STDIO_LOG="$LOG_DIR/run_${RUN_TS}.stdio.log"

set +e
python3 "$FN_DIR/run.py" "$@" 2>&1 | tee "$STDIO_LOG"
rc=${PIPESTATUS[0]}
set -e
exit "$rc"

