#!/usr/bin/env bash
# Perf #2: 100,000 object mixed workload. Target avg <= 50us, P99 <= 100us.
#
# Rationale: run nr_bench with mix op at a moderate thread count to capture a
# realistic latency distribution. We use a duration long enough (>=10s at
# ~100k ops/s per thread) to guarantee >>100k samples for the histogram.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
BIN="$ROOT/build/bin/nr_bench"
UDS="${UDS:-/tmp/native_rdma-dp.sock}"
DUR="${DUR:-10}"
THREADS="${THREADS:-8}"
OUT_DIR="${OUT_DIR:-$ROOT/logs/perf}"
TS="$(date +%Y%m%d_%H%M%S)"
mkdir -p "$OUT_DIR"
OUT="$OUT_DIR/perf_02_latency_${TS}.json"

[ -x "$BIN" ] || { echo "nr_bench missing: $BIN" >&2; exit 2; }
[ -S "$UDS" ] || { echo "data plane not running (no $UDS)" >&2; exit 2; }

echo ">>> perf#2 threads=$THREADS val=1024 dur=${DUR}s op=mix" >&2
raw=$("$BIN" --uds="$UDS" --op=mix --threads="$THREADS" \
             --val-size=1024 --duration="$DUR" 2>&1)
echo "$raw" >&2
j=$(echo "$raw" | python3 "$ROOT/tests/performance/parse_bench.py")

python3 - "$OUT" "$j" <<'PY'
import json, sys
out_path, j_text = sys.argv[1], sys.argv[2]
j = json.loads(j_text)
avg = float(j.get("lat_avg_us", 1e9))
p99 = float(j.get("lat_p99_us", 1e9))
ok  = int(j.get("ops_ok", 0))
passed = (ok >= 100_000) and (avg <= 50.0) and (p99 <= 100.0)
result = {
    "metric":     "perf_02_latency",
    "samples":    ok,
    "lat_avg_us": avg,
    "lat_p50_us": float(j.get("lat_p50_us", 0)),
    "lat_p99_us": p99,
    "lat_p99_9_us": float(j.get("lat_p99_9_us", 0)),
    "lat_max_us": float(j.get("lat_max_us", 0)),
    "thresholds": {"samples": 100_000, "avg_us": 50.0, "p99_us": 100.0},
    "passed":     bool(passed),
    "raw":        j,
}
with open(out_path, "w") as f: json.dump(result, f, indent=2)
print(json.dumps(result, indent=2))
PY

echo "[done] $OUT"
