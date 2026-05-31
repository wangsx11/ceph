#!/usr/bin/env bash
set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
OUT_DIR="${OUT_DIR:-${SCRIPT_DIR}}"
DUR="${DUR:-5}"
THREADS="${THREADS:-1}"
QUEUE_DEPTH="${QUEUE_DEPTH:-1}"
PF7_BACKEND="${PF7_BACKEND:-dataplane}"
PF7_WARMUP_OPS="${PF7_WARMUP_OPS:-100}"

export REPO_ROOT OUT_DIR DUR THREADS QUEUE_DEPTH PF7_BACKEND PF7_WARMUP_OPS

echo "[PF-7] output directory: ${OUT_DIR}"
echo "[PF-7] running performance test and updating summary.md"
python3 "${SCRIPT_DIR}/run.py" "$@"
exit $?
