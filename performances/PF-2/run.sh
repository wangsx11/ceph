#!/usr/bin/env bash
set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
OUT_DIR="${OUT_DIR:-${SCRIPT_DIR}}"
UDS="${UDS:-/tmp/native_rdma-dp.sock}"
CTRL_URL="${CTRL_URL:-http://127.0.0.1:5000}"
REQUIRE_PEER="${REQUIRE_PEER:-1}"
PF2_TARGET_SAMPLES="${PF2_TARGET_SAMPLES:-110000}"
PF2_SAMPLE_MARGIN="${PF2_SAMPLE_MARGIN:-20000}"
PF2_MEASURED_DUR="${PF2_MEASURED_DUR:-4}"
PF2_MEASURED_MAX_IOPS="${PF2_MEASURED_MAX_IOPS:-30000}"

export REPO_ROOT OUT_DIR UDS CTRL_URL REQUIRE_PEER
export PF2_TARGET_SAMPLES PF2_SAMPLE_MARGIN PF2_MEASURED_DUR PF2_MEASURED_MAX_IOPS

echo "[PF-2] output directory: ${OUT_DIR}"
echo "[PF-2] running performance test and updating summary.md"
python3 "${SCRIPT_DIR}/run.py" "$@"
exit $?
