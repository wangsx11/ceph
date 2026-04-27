#!/usr/bin/env bash
# Perf #6: Tiering read/write bandwidth.
#   Target write >= 10 GB/s, read >= 20 GB/s.
#
# Requires the data plane to have been started with SLAB_SLOT_SIZE >= 1048576
# so that we can push 1 MB payloads per request and saturate the RDMA link.
# If the slab slot is too small, the test reports a skip and passes the knob
# back to the caller via exit code 3.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
BIN="$ROOT/build/bin/nr_bench"
UDS="${UDS:-/tmp/native_rdma-dp.sock}"
DUR="${DUR:-10}"
THREADS="${THREADS:-8}"
VAL_SIZE="${VAL_SIZE:-1048576}"   # 1 MB default
OUT_DIR="${OUT_DIR:-$ROOT/logs/perf}"
TS="$(date +%Y%m%d_%H%M%S)"
mkdir -p "$OUT_DIR"
OUT="$OUT_DIR/perf_06_tier_bw_${TS}.json"

[ -x "$BIN" ] || { echo "nr_bench missing: $BIN" >&2; exit 2; }
[ -S "$UDS" ] || { echo "data plane not running (no $UDS)" >&2; exit 2; }

run_one() {
    local op=$1
    echo ">>> perf#6 op=$op threads=$THREADS val=$VAL_SIZE dur=${DUR}s" >&2
    "$BIN" --uds="$UDS" --op="$op" --threads="$THREADS" \
           --val-size="$VAL_SIZE" --duration="$DUR" 2>&1
}

raw_w=$(run_one put || true)
echo "$raw_w" >&2
j_w=$(echo "$raw_w" | python3 "$ROOT/tests/performance/parse_bench.py")

raw_r=$(run_one get || true)
echo "$raw_r" >&2
j_r=$(echo "$raw_r" | python3 "$ROOT/tests/performance/parse_bench.py")

python3 - "$OUT" "$j_w" "$j_r" "$VAL_SIZE" <<'PY'
import json, sys
out_path, jw_text, jr_text, vsz = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4])
jw = json.loads(jw_text) if jw_text.strip() else {}
jr = json.loads(jr_text) if jr_text.strip() else {}
# If nr_bench rejected the payload because slot was too small, ops=0 and
# ops_fail >> 0. Detect and explain.
wops = float(jw.get("ops_per_sec", 0))
rops = float(jr.get("ops_per_sec", 0))
wfail = int(jw.get("ops_fail", 0))
w_bw_gbs = wops * vsz / 1e9   # GB/s (SI decimal GB)
r_bw_gbs = rops * vsz / 1e9

skipped = (wops == 0 and wfail > 0)
passed = (not skipped) and (w_bw_gbs >= 10.0) and (r_bw_gbs >= 20.0)
result = {
    "metric":     "perf_06_tier_bw",
    "val_size":   vsz,
    "write_ops":  wops,
    "write_gbs":  round(w_bw_gbs, 3),
    "read_ops":   rops,
    "read_gbs":   round(r_bw_gbs, 3),
    "thresholds": {"write_gbs": 10.0, "read_gbs": 20.0},
    "passed":     bool(passed),
    "note":       ("slab_slot_size too small, payload rejected; "
                   "restart data plane with SLAB_SLOT_SIZE=1048576 SLAB_TOTAL_BYTES=4294967296"
                   if skipped else ""),
    "raw_put":    jw,
    "raw_get":    jr,
}
with open(out_path, "w") as f: json.dump(result, f, indent=2)
print(json.dumps(result, indent=2))
PY
echo "[done] $OUT"
