#!/usr/bin/env bash
# Perf #5: Batch throughput >= 700 MB/s for 1 KB writes.
# MB/s = ops/s * val_size / 1e6
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
BIN="$ROOT/build/bin/nr_bench"
UDS="${UDS:-/tmp/native_rdma-dp.sock}"
DUR="${DUR:-15}"
THREADS="${THREADS:-16}"
REQUIRE_PEER="${REQUIRE_PEER:-1}"
OUT_DIR="${OUT_DIR:-$ROOT/logs/perf}"
TS="$(date +%Y%m%d_%H%M%S)"
mkdir -p "$OUT_DIR"
OUT="$OUT_DIR/perf_05_batch_bw_${TS}.json"

[ -x "$BIN" ] || { echo "nr_bench missing: $BIN" >&2; exit 2; }
[ -S "$UDS" ] || { echo "data plane not running (no $UDS)" >&2; exit 2; }

echo ">>> perf#5 batch throughput threads=$THREADS val=1024 dur=${DUR}s" >&2
raw=$("$BIN" --uds="$UDS" --op=put --threads="$THREADS" \
             --val-size=1024 --duration="$DUR" \
             --require-peer="$REQUIRE_PEER" 2>&1)
echo "$raw" >&2
j=$(echo "$raw" | python3 "$ROOT/tests/performance/parse_bench.py")

python3 - "$OUT" "$j" <<'PY'
import json, sys
out_path, j_text = sys.argv[1], sys.argv[2]
j = json.loads(j_text)
ops = float(j.get("ops_per_sec", 0))
sz  = int(j.get("val_size", 1024))
fail = int(j.get("ops_fail", 0))
degr = int(j.get("ops_degraded", 0))
mbs = ops * sz / 1e6
passed = mbs >= 700.0 and fail == 0 and degr == 0
result = {
    "metric":     "perf_05_batch_bw",
    "ops_per_sec": ops,
    "ops_fail":    fail,
    "ops_degraded": degr,
    "val_size":   sz,
    "mb_per_sec": round(mbs, 2),
    "threshold_mbs": 700.0,
    "passed":     bool(passed),
    "raw":        j,
}
with open(out_path, "w") as f: json.dump(result, f, indent=2)
print(json.dumps(result, indent=2))
PY
echo "[done] $OUT"
