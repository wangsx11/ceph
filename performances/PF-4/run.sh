#!/usr/bin/env bash
set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
OUT_DIR="${OUT_DIR:-${SCRIPT_DIR}}"
UDS="${UDS:-/tmp/native_rdma-dp.sock}"
CTRL_URL="${CTRL_URL:-http://127.0.0.1:5000}"
REQUIRE_PEER="${REQUIRE_PEER:-1}"
MEASURED_RUNS_A="${MEASURED_RUNS_A:-3}"
MEASURED_RUNS_B="${MEASURED_RUNS_B:-10}"
PF4_RESTART="${PF4_RESTART:-1}"
NR_ASYNC_REPL="${NR_ASYNC_REPL:-1}"

export REPO_ROOT OUT_DIR UDS CTRL_URL REQUIRE_PEER MEASURED_RUNS_A MEASURED_RUNS_B PF4_RESTART NR_ASYNC_REPL

echo "[PF-4] output directory: ${OUT_DIR}"
echo "[PF-4] running performance test and updating summary.md"
python3 "${SCRIPT_DIR}/run.py" "$@"
exit $?
