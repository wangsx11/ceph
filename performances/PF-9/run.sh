#!/usr/bin/env bash
set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
OUT_DIR="${OUT_DIR:-${SCRIPT_DIR}}"
THREADS="${THREADS:-8}"
OBJECT_SIZE="${OBJECT_SIZE:-1024}"
MEASURED_RUNS="${MEASURED_RUNS:-3}"

export REPO_ROOT OUT_DIR THREADS OBJECT_SIZE MEASURED_RUNS

echo "[PF-9] output directory: ${OUT_DIR}"
echo "[PF-9] running performance test and updating summary.md"
python3 "${SCRIPT_DIR}/run.py" "$@"
exit $?
