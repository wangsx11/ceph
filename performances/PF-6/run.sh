#!/usr/bin/env bash
set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
OUT_DIR="${OUT_DIR:-${SCRIPT_DIR}}"
UDS="${UDS:-/tmp/native_rdma-dp.sock}"
CTRL_URL="${CTRL_URL:-http://127.0.0.1:5000}"
REQUIRE_PEER="${REQUIRE_PEER:-1}"
NR_SKIP_FLASK="${NR_SKIP_FLASK:-1}"
WRITE_DUR="${WRITE_DUR:-3}"
READ_DUR="${READ_DUR:-3}"
PF6_DRAIN_SECONDS="${PF6_DRAIN_SECONDS:-8}"
PF6_STABILIZE_S="${PF6_STABILIZE_S:-3}"
PUT_THREADS="${PUT_THREADS:-6}"
PUT_BATCH="${PUT_BATCH:-2}"
GET_THREADS="${GET_THREADS:-12}"

export REPO_ROOT OUT_DIR UDS CTRL_URL REQUIRE_PEER NR_SKIP_FLASK WRITE_DUR READ_DUR PF6_DRAIN_SECONDS PF6_STABILIZE_S PUT_THREADS PUT_BATCH GET_THREADS

echo "[PF-6] output directory: ${OUT_DIR}"
echo "[PF-6] running performance test and updating summary.md"
python3 "${SCRIPT_DIR}/run.py" "$@"
exit $?
