#!/usr/bin/env bash
# One-shot driver for the performance matrix.
#
# Runs perf_01..perf_09 (those that are implemented today), aggregates the
# JSON outputs in logs/perf/, then feeds them through summary.py to produce
# a Markdown matrix. Each script is run best-effort; a single failure does not
# abort the rest -- we want a report for every metric even if some fail, so
# summary.py can surface them as FAIL.
#
# Env knobs forwarded to child scripts:
#   UDS, DUR, THREADS, LINK_GBPS
set -u
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
HERE="$ROOT/tests/performance"

echo "== perf matrix driver =="
echo "ROOT=$ROOT"
mkdir -p "$ROOT/logs/perf"

declare -a SCRIPTS=(
    "perf_01_ops_1kb.sh"
    "perf_02_latency.sh"
    "perf_04_batch_latency.sh"
    "perf_05_batch_bw.sh"
    "perf_09_mempool.sh"
    # perf_06_tier_bw.sh requires SLAB_SLOT_SIZE>=1MB at DP startup; opt-in
    # via TEST_TIER_BW=1 so run_all.sh doesn't fail on a 1KB-slot deployment.
)
if [ "${TEST_TIER_BW:-0}" = "1" ]; then
    SCRIPTS+=("perf_06_tier_bw.sh")
fi

for s in "${SCRIPTS[@]}"; do
    echo
    echo "================================================================"
    echo "==> $s"
    echo "================================================================"
    if bash "$HERE/$s"; then
        echo "[ok]  $s"
    else
        echo "[err] $s (continuing)"
    fi
done

echo
echo "================================================================"
echo "==> summary"
echo "================================================================"
python3 "$HERE/summary.py"
