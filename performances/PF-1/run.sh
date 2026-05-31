#!/usr/bin/env bash
set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
OUT_DIR="${OUT_DIR:-${SCRIPT_DIR}}"
UDS="${UDS:-/tmp/native_rdma-dp.sock}"
CTRL_URL="${CTRL_URL:-http://127.0.0.1:5000}"
REQUIRE_PEER="${REQUIRE_PEER:-1}"
DUR="${DUR:-4}"
BW_THREADS_LIST="${BW_THREADS_LIST:-4}"
PF1_BW_WARMUP_DUR="${PF1_BW_WARMUP_DUR:-1}"
PF1_READY_WAIT_S="${PF1_READY_WAIT_S:-1}"
PF1_OPS_STABILIZE_S="${PF1_OPS_STABILIZE_S:-1}"

export REPO_ROOT OUT_DIR UDS CTRL_URL REQUIRE_PEER DUR BW_THREADS_LIST PF1_BW_WARMUP_DUR PF1_READY_WAIT_S PF1_OPS_STABILIZE_S

echo "[PF-1] output directory: ${OUT_DIR}"
echo "[PF-1] running performance test and updating summary.md"
python3 "${SCRIPT_DIR}/run.py" "$@"
exit $?
