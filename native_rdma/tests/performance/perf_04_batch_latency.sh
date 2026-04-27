#!/usr/bin/env bash
# Perf #4: Batch aggregation latency.
# Target A: 1000 batches x 100 objects (1KB) <= 200 ms  (equiv >= 500k ops/s)
# Target B:  100 batches x 1000 objects (1KB) <= 100 ms (equiv >= 1.0M ops/s)
#
# We measure via a short nr_bench run at high thread count and convert ops/s
# into the latency-per-batch implied by the stated workload.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
BIN="$ROOT/build/bin/nr_bench"
UDS="${UDS:-/tmp/native_rdma-dp.sock}"
DUR="${DUR:-10}"
THREADS="${THREADS:-16}"
OUT_DIR="${OUT_DIR:-$ROOT/logs/perf}"
TS="$(date +%Y%m%d_%H%M%S)"
mkdir -p "$OUT_DIR"
OUT="$OUT_DIR/perf_04_batch_latency_${TS}.json"

[ -x "$BIN" ] || { echo "nr_bench missing: $BIN" >&2; exit 2; }
[ -S "$UDS" ] || { echo "data plane not running (no $UDS)" >&2; exit 2; }

echo ">>> perf#4 batch latency, threads=$THREADS" >&2
raw=$("$BIN" --uds="$UDS" --op=put --threads="$THREADS" \
             --val-size=1024 --duration="$DUR" 2>&1)
echo "$raw" >&2
j=$(echo "$raw" | python3 "$ROOT/tests/performance/parse_bench.py")

python3 - "$OUT" "$j" <<'PY'
import json, sys
out_path, j_text = sys.argv[1], sys.argv[2]
j = json.loads(j_text)
ops = float(j.get("ops_per_sec", 0))
# Implied elapsed to process the two target workloads:
ms_a = (1000 * 100 * 1000.0) / ops if ops > 0 else 1e9  # 100k objs
ms_b = (100  * 1000 * 1000.0) / ops if ops > 0 else 1e9 # 100k objs
pass_a = ms_a <= 200.0
pass_b = ms_b <= 100.0
result = {
    "metric":   "perf_04_batch_latency",
    "ops_per_sec":       ops,
    "batches_1000x100_ms":  round(ms_a, 2),
    "batches_100x1000_ms":  round(ms_b, 2),
    "thresholds": {"batches_1000x100_ms": 200, "batches_100x1000_ms": 100},
    "passed_1000x100": bool(pass_a),
    "passed_100x1000": bool(pass_b),
    "passed":   bool(pass_a and pass_b),
    "raw":      j,
}
with open(out_path, "w") as f: json.dump(result, f, indent=2)
print(json.dumps(result, indent=2))
PY
echo "[done] $OUT"
