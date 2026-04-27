#!/usr/bin/env bash
# Perf #1: 1 KB PUT, target 1,000,000 ops/s and bandwidth utilization >= 50%.
#
# Sweeps thread count from 8..32 and keeps the best ops/s value.
# Utilization is ops/s * val_size * 8 / link_gbps.
#
# Env knobs:
#   UDS=/tmp/native_rdma-dp.sock   path to data plane UDS
#   DUR=15                         seconds per run
#   LINK_GBPS=100                  theoretical link bandwidth (used for %)
#   OUT_DIR=logs/perf              where to drop the JSON report
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
BIN="$ROOT/build/bin/nr_bench"
UDS="${UDS:-/tmp/native_rdma-dp.sock}"
DUR="${DUR:-15}"
LINK_GBPS="${LINK_GBPS:-100}"
OUT_DIR="${OUT_DIR:-$ROOT/logs/perf}"
TS="$(date +%Y%m%d_%H%M%S)"
mkdir -p "$OUT_DIR"
OUT="$OUT_DIR/perf_01_ops_1kb_${TS}.json"

[ -x "$BIN" ] || { echo "nr_bench missing: $BIN" >&2; exit 2; }
[ -S "$UDS" ] || { echo "data plane not running (no $UDS)" >&2; exit 2; }

best_ops=0
best_json='{}'
best_threads=0

for t in 8 16 24 32; do
    echo ">>> perf#1 threads=$t val=1024 dur=${DUR}s" >&2
    raw=$("$BIN" --uds="$UDS" --op=put --threads="$t" \
                 --val-size=1024 --duration="$DUR" 2>&1 || true)
    echo "$raw" >&2
    j=$(echo "$raw" | python3 "$ROOT/tests/performance/parse_bench.py")
    ops=$(echo "$j" | python3 -c "import json,sys; print(int(json.load(sys.stdin).get('ops_per_sec',0)))")
    if [ "$ops" -gt "$best_ops" ]; then
        best_ops=$ops
        best_json=$j
        best_threads=$t
    fi
done

python3 - "$OUT" "$best_json" "$best_threads" "$LINK_GBPS" <<'PY'
import json, sys
out_path, j_text, threads, link_gbps = sys.argv[1], sys.argv[2], int(sys.argv[3]), float(sys.argv[4])
j = json.loads(j_text) if j_text.strip() else {}
ops   = float(j.get("ops_per_sec", 0))
vsz   = int(j.get("val_size", 1024))
# Raw user payload bandwidth (does not include RDMA headers).
bw_bps    = ops * vsz * 8.0
bw_gbps   = bw_bps / 1e9
util_pct  = (bw_gbps / link_gbps) * 100.0 if link_gbps > 0 else 0.0

passed = (ops >= 1_000_000) and (util_pct >= 50.0)
result = {
    "metric":     "perf_01_ops_1kb",
    "threads":    threads,
    "val_size":   vsz,
    "ops_per_sec": ops,
    "bw_gbps":    round(bw_gbps, 3),
    "link_gbps":  link_gbps,
    "util_pct":   round(util_pct, 2),
    "thresholds": {"ops_per_sec": 1_000_000, "util_pct": 50.0},
    "passed":     bool(passed),
    "raw":        j,
}
with open(out_path, "w") as f: json.dump(result, f, indent=2)
print(json.dumps(result, indent=2))
PY

echo "[done] $OUT"
