#!/usr/bin/env bash
# Perf #3: QoS high-priority advantage over low-priority under contention.
# Target per docs/自研实施清单.md §7 row #3: gain_pct >= 22%.
#
# Method: run two nr_bench instances concurrently, one tagged --prio=hi
# (2 dedicated QPs, prioritized CQ polling) and one tagged --prio=lo
# (6 shared QPs). Compare ops/s.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
BIN="$ROOT/build/bin/nr_bench"
UDS="${UDS:-/tmp/native_rdma-dp.sock}"
DUR="${DUR:-10}"
THREADS="${THREADS:-8}"
OUT_DIR="${OUT_DIR:-$ROOT/logs/perf}"
TS="$(date +%Y%m%d_%H%M%S)"
mkdir -p "$OUT_DIR"
OUT="$OUT_DIR/perf_03_qos_${TS}.json"
TMP_HI="$(mktemp)"
TMP_LO="$(mktemp)"
trap 'rm -f "$TMP_HI" "$TMP_LO"' EXIT

[ -x "$BIN" ] || { echo "nr_bench missing: $BIN" >&2; exit 2; }
[ -S "$UDS" ] || { echo "data plane not running (no $UDS)" >&2; exit 2; }

echo ">>> perf#3 QoS: hi + lo concurrent, threads=$THREADS each, dur=${DUR}s" >&2

# Launch both in parallel.  Keyspace disjoint so they don't collide.
"$BIN" --uds="$UDS" --op=put --prio=hi --threads="$THREADS" \
       --val-size=1024 --duration="$DUR" --keyspace=5000 > "$TMP_HI" 2>&1 &
PID_HI=$!
"$BIN" --uds="$UDS" --op=put --prio=lo --threads="$THREADS" \
       --val-size=1024 --duration="$DUR" --keyspace=5000 > "$TMP_LO" 2>&1 &
PID_LO=$!
wait "$PID_HI" "$PID_LO" || true

echo "---- hi ----" >&2; cat "$TMP_HI" >&2
echo "---- lo ----" >&2; cat "$TMP_LO" >&2

j_hi=$(python3 "$ROOT/tests/performance/parse_bench.py" < "$TMP_HI")
j_lo=$(python3 "$ROOT/tests/performance/parse_bench.py" < "$TMP_LO")

python3 - "$OUT" "$j_hi" "$j_lo" <<'PY'
import json, sys
out_path, jh, jl = sys.argv[1], sys.argv[2], sys.argv[3]
hi = json.loads(jh) if jh.strip() else {}
lo = json.loads(jl) if jl.strip() else {}
hi_ops = float(hi.get("ops_per_sec", 0))
lo_ops = float(lo.get("ops_per_sec", 0))
# Gain = (hi - lo) / lo * 100%.  Positive => high-prio has an advantage.
gain_pct = ((hi_ops - lo_ops) / lo_ops * 100.0) if lo_ops > 0 else 0.0
passed = gain_pct >= 22.0
result = {
    "metric":     "perf_03_qos",
    "hi_ops":     hi_ops,
    "lo_ops":     lo_ops,
    "hi_p99_us":  hi.get("lat_p99_us", 0),
    "lo_p99_us":  lo.get("lat_p99_us", 0),
    "gain_pct":   round(gain_pct, 2),
    "threshold_gain_pct": 22.0,
    "passed":     bool(passed),
    "raw_hi":     hi,
    "raw_lo":     lo,
}
with open(out_path, "w") as f: json.dump(result, f, indent=2)
print(json.dumps(result, indent=2))
PY
echo "[done] $OUT"
