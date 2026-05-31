#!/usr/bin/env bash
set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
OUT_DIR="${OUT_DIR:-${SCRIPT_DIR}}"
UDS="${UDS:-/tmp/native_rdma-dp.sock}"
CTRL_URL="${CTRL_URL:-http://127.0.0.1:5000}"
REQUIRE_PEER="${REQUIRE_PEER:-1}"
DUR="${DUR:-1}"
PF5_STABILIZE_S="${PF5_STABILIZE_S:-0.2}"
PF5_WARMUP_DUR="${PF5_WARMUP_DUR:-0}"

export REPO_ROOT OUT_DIR UDS CTRL_URL REQUIRE_PEER DUR PF5_STABILIZE_S PF5_WARMUP_DUR

echo "[PF-5] output directory: ${OUT_DIR}"
echo "[PF-5] running performance test and updating summary.md"
python3 "${SCRIPT_DIR}/run.py" "$@"
exit $?
