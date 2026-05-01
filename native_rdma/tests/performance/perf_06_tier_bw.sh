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
REQUIRE_PEER="${REQUIRE_PEER:-1}"
OUT_DIR="${OUT_DIR:-$ROOT/logs/perf}"
TS="$(date +%Y%m%d_%H%M%S)"
mkdir -p "$OUT_DIR"
OUT="$OUT_DIR/perf_06_tier_bw_${TS}.json"

[ -x "$BIN" ] || { echo "nr_bench missing: $BIN" >&2; exit 2; }
[ -S "$UDS" ] || { echo "data plane not running (no $UDS)" >&2; exit 2; }

# PUT and GET have different bottlenecks at 1MB payload:
#   * PUT is bottlenecked by RDMA WRITE round-trip latency to the peer --
#     more concurrent writers -> more in-flight WRs on the wire -> higher
#     aggregate bandwidth. 16 threads is empirically enough to saturate
#     the 100 Gbps link.
#   * GET is bottlenecked by UDS kernel-to-user copy; 8 threads already
#     approaches the DDR-copy ceiling.
PUT_THREADS="${PUT_THREADS:-16}"
GET_THREADS="${GET_THREADS:-$THREADS}"

run_one() {
    local op=$1
    local dur=$2
    local th=$3
    echo ">>> perf#6 op=$op threads=$th val=$VAL_SIZE keyspace=$KEYSPACE(shared) dur=${dur}s" >&2
    # --shared-keyspace is crucial: all threads (and all three phases --
    # write, warmup, read) touch the SAME $KEYSPACE keys. Without this
    # flag nr_bench prefixes each key with its thread id, so 16-thread
    # warmup would create 16*$KEYSPACE distinct keys. At val_size=1MB
    # and keyspace=512 that is 8GB -- it overflows a 4GB slab, leaves
    # many PUTs failing with "slab oom", and the subsequent 8-thread
    # GET phase reads a partly-populated keyspace => mostly misses =>
    # read bandwidth is inflated by tiny "not found" replies. With
    # shared-keyspace the footprint is fixed at $KEYSPACE * val_size
    # (512 MB), well within any reasonable slab.
    "$BIN" --uds="$UDS" --op="$op" --threads="$th" \
           --val-size="$VAL_SIZE" --duration="$dur" \
           --keyspace="$KEYSPACE" --shared-keyspace=1 \
           --require-peer="$REQUIRE_PEER" 2>&1
}

# Phase 1: write throughput (16 threads to saturate RDMA link).
raw_w=$(run_one put "$DUR" "$PUT_THREADS" || true)
echo "$raw_w" >&2
j_w=$(echo "$raw_w" | python3 "$ROOT/tests/performance/parse_bench.py")

# Phase 2 warmup: make sure every key in the keyspace has a 1MB value
# so phase 3 GETs can hit. 3 seconds at ~1GB/s * 8 threads is several GB,
# way more than KEYSPACE * 1MB = 512MB.
raw_warm=$(run_one put 3 "$PUT_THREADS" || true)
echo "(warmup complete)" >&2

# Phase 3: read throughput (uses RPC_KV_GET_RAW which really transmits
# the whole payload back to the client).
raw_r=$(run_one get-raw "$DUR" "$GET_THREADS" || true)
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
wdegr = int(jw.get("ops_degraded", 0))
rfail = int(jr.get("ops_fail", 0))

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

# Sanity: what fraction of GET responses look full-size? A healthy run
# has avg_resp ≈ val_size + 5B header ⇒ hit_ratio ≈ 1.000005. If it drops
# below 0.95 we probably got "not found" replies and bandwidth is
# overstated (miss inflation). If it sits above 1.05 something is wrong
# in the accounting layer (e.g. bytes counter double-counting) and the
# number should not be trusted.
# NB: divide by ops_ok (the total count) NOT ops_per_sec -- the latter
# already divides by elapsed_s and would produce a 10x-inflated avg_resp
# for a 10-second run.
rops_total = int(jr.get("ops_ok", 0))
rops_per_s = float(jr.get("ops_per_sec", 0))
avg_resp = (r_rx_bytes / rops_total) if rops_total > 0 else 0
hit_ratio = avg_resp / vsz if vsz > 0 else 0
hit_lo, hit_hi = 0.95, 1.05

skipped = (wops == 0 and wfail > 0)
passed = (not skipped) \
    and (w_bw_gbs >= 10.0) \
    and (r_bw_gbs >= 20.0) \
    and (hit_lo <= hit_ratio <= hit_hi) \
    and wfail == 0 and wdegr == 0 and rfail == 0

result = {
    "metric":     "perf_06_tier_bw",
    "val_size":   vsz,
    "keyspace":   int(jr.get("val_size", 0) or 0) and None,  # not essential
    "write_ops":  wops,
    "write_fail": wfail,
    "write_degraded": wdegr,
    "write_tx_bytes": w_tx_bytes,
    "write_gbs":  round(w_bw_gbs, 3),
    "read_ops":   rops_per_s,
    "read_fail":  rfail,
    "read_ops_total": rops_total,
    "read_rx_bytes":  r_rx_bytes,
    "read_gbs":   round(r_bw_gbs, 3),
    "read_avg_resp_bytes": int(avg_resp),
    "read_hit_ratio":      round(hit_ratio, 4),
    "thresholds": {"write_gbs": 10.0, "read_gbs": 20.0,
                   "hit_ratio_min": hit_lo, "hit_ratio_max": hit_hi},
    "passed":     bool(passed),
    "note":       ("slab_slot_size too small, payload rejected; "
                   "restart data plane with SLAB_SLOT_SIZE=1048576 SLAB_TOTAL_BYTES=4294967296"
                   if skipped else
                   ("LOW HIT RATIO %.4f: GETs mostly missed, bandwidth overstated"
                    % hit_ratio if hit_ratio < hit_lo else
                    ("ANOMALOUS HIT RATIO %.4f: avg_resp is %d B vs val_size %d B -- "
                     "suspect accounting bug, bandwidth not trustworthy"
                     % (hit_ratio, int(avg_resp), vsz) if hit_ratio > hit_hi else ""))),
    "raw_put":    jw,
    "raw_get":    jr,
}
with open(out_path, "w") as f: json.dump(result, f, indent=2)
print(json.dumps(result, indent=2))
PY
echo "[done] $OUT"
