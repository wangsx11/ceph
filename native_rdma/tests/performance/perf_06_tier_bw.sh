#!/usr/bin/env bash
# Perf #6: Tiering read/write bandwidth (rigorous).
#   Target write >= 10 GB/s, read >= 20 GB/s.
#
# Methodology:
#   1. Write phase: nr_bench --op=put --val-size=1MB saturates RDMA WRITE to
#      the peer (and the local slab memcpy + index update).
#   2. Warmup: a short put-only pass populates every key the GET phase will
#      touch -- otherwise get-raw would mostly miss, the server would reply
#      with 5-byte "not found" responses, and bandwidth would be
#      overstated.
#   3. Read phase: nr_bench --op=get-raw hits RPC_KV_GET_RAW which actually
#      writes the full payload to UDS.
#
# Crucially we report bandwidth using nr_bench's `resp_bytes` counter
# (real bytes received from UDS), NOT the old `ops_per_sec * val_size`
# formula, because that was vulnerable to (a) GET miss inflation and
# (b) short-response RPCs inflating the per-op payload accounting.
#
# Requires SLAB_SLOT_SIZE >= 1048576 in the running data plane so 1MB
# PUTs are accepted.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
BIN="$ROOT/build/bin/nr_bench"
UDS="${UDS:-/tmp/native_rdma-dp.sock}"
DUR="${DUR:-10}"
THREADS="${THREADS:-8}"
VAL_SIZE="${VAL_SIZE:-1048576}"   # 1 MB default
KEYSPACE="${KEYSPACE:-512}"       # small so warmup fills the space quickly
OUT_DIR="${OUT_DIR:-$ROOT/logs/perf}"
TS="$(date +%Y%m%d_%H%M%S)"
mkdir -p "$OUT_DIR"
OUT="$OUT_DIR/perf_06_tier_bw_${TS}.json"

[ -x "$BIN" ] || { echo "nr_bench missing: $BIN" >&2; exit 2; }
[ -S "$UDS" ] || { echo "data plane not running (no $UDS)" >&2; exit 2; }

run_one() {
    local op=$1
    local dur=$2
    echo ">>> perf#6 op=$op threads=$THREADS val=$VAL_SIZE keyspace=$KEYSPACE dur=${dur}s" >&2
    "$BIN" --uds="$UDS" --op="$op" --threads="$THREADS" \
           --val-size="$VAL_SIZE" --duration="$dur" \
           --keyspace="$KEYSPACE" 2>&1
}

# Phase 1: write throughput.
raw_w=$(run_one put "$DUR" || true)
echo "$raw_w" >&2
j_w=$(echo "$raw_w" | python3 "$ROOT/tests/performance/parse_bench.py")

# Phase 2 warmup: make sure every key in the keyspace has a 1MB value
# so phase 3 GETs can hit. 3 seconds at ~1GB/s * 8 threads is several GB,
# way more than KEYSPACE * 1MB = 512MB.
raw_warm=$(run_one put 3 || true)
echo "(warmup complete)" >&2

# Phase 3: read throughput (uses RPC_KV_GET_RAW which really transmits
# the whole payload back to the client).
raw_r=$(run_one get-raw "$DUR" || true)
echo "$raw_r" >&2
j_r=$(echo "$raw_r" | python3 "$ROOT/tests/performance/parse_bench.py")

python3 - "$OUT" "$j_w" "$j_r" "$VAL_SIZE" <<'PY'
import json, sys
out_path, jw_text, jr_text, vsz = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4])
jw = json.loads(jw_text) if jw_text.strip() else {}
jr = json.loads(jr_text) if jr_text.strip() else {}

wops  = float(jw.get("ops_per_sec", 0))
rops  = float(jr.get("ops_per_sec", 0))
wfail = int(jw.get("ops_fail", 0))

# BYTE-BASED bandwidth. For writes we use req_bytes (what we sent over
# UDS as the PUT body, which the server then replicates via RDMA WRITE
# and stores locally). For reads we use resp_bytes (what the server
# actually shipped back through UDS). Either avoids the classic
# "ops * assumed_payload" pitfall -- e.g. if a GET misses, resp_bytes
# only counts the 5-byte short response.
elapsed_w = float(jw.get("elapsed_s", 0)) or 1.0
elapsed_r = float(jr.get("elapsed_s", 0)) or 1.0
w_tx_bytes = int(jw.get("req_bytes", 0))    # PUT: client->server payload
r_rx_bytes = int(jr.get("resp_bytes", 0))   # GET: server->client payload
w_bw_gbs   = (w_tx_bytes / elapsed_w) / 1e9
r_bw_gbs   = (r_rx_bytes / elapsed_r) / 1e9

# Sanity: what fraction of GET responses look full-size? If <80%, the
# hit ratio is too low and the bandwidth is not meaningful.
avg_resp = (r_rx_bytes / rops) if rops > 0 else 0
hit_ratio = avg_resp / vsz if vsz > 0 else 0

skipped = (wops == 0 and wfail > 0)
passed = (not skipped) \
    and (w_bw_gbs >= 10.0) \
    and (r_bw_gbs >= 20.0) \
    and (hit_ratio >= 0.80)    # reject the test if GETs mostly missed

result = {
    "metric":     "perf_06_tier_bw",
    "val_size":   vsz,
    "keyspace":   int(jr.get("val_size", 0) or 0) and None,  # not essential
    "write_ops":  wops,
    "write_tx_bytes": w_tx_bytes,
    "write_gbs":  round(w_bw_gbs, 3),
    "read_ops":   rops,
    "read_rx_bytes":  r_rx_bytes,
    "read_gbs":   round(r_bw_gbs, 3),
    "read_avg_resp_bytes": int(avg_resp),
    "read_hit_ratio":      round(hit_ratio, 3),
    "thresholds": {"write_gbs": 10.0, "read_gbs": 20.0, "min_hit_ratio": 0.80},
    "passed":     bool(passed),
    "note":       ("slab_slot_size too small, payload rejected; "
                   "restart data plane with SLAB_SLOT_SIZE=1048576 SLAB_TOTAL_BYTES=4294967296"
                   if skipped else
                   ("LOW HIT RATIO %.2f: GETs mostly missed, bandwidth not trustworthy"
                    % hit_ratio if hit_ratio < 0.80 else "")),
    "raw_put":    jw,
    "raw_get":    jr,
}
with open(out_path, "w") as f: json.dump(result, f, indent=2)
print(json.dumps(result, indent=2))
PY
echo "[done] $OUT"
