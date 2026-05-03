#!/usr/bin/env bash
set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
OUT_DIR="${OUT_DIR:-${SCRIPT_DIR}}"
CTRL_URL="${CTRL_URL:-http://127.0.0.1:5000}"
UDS="${UDS:-/tmp/native_rdma-dp.sock}"
SIM_NODES="${SIM_NODES:-4}"
ENTITIES="${ENTITIES:-100000}"
EVENTS="${EVENTS:-1000000}"

export REPO_ROOT OUT_DIR CTRL_URL UDS SIM_NODES ENTITIES EVENTS

echo "[PF-8] output directory: ${OUT_DIR}"
echo "[PF-8] running performance test and updating summary.md"
python3 "${SCRIPT_DIR}/run.py" "$@"
exit $?
