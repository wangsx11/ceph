#!/usr/bin/env bash
# Bandwidth-oriented bench: large values, few threads, stress the RDMA WRITE path.
# Runs several shape combos and reports MB/s + Gbps + CPU util from /proc/stat
# delta. Outputs a Markdown summary under logs/bench_bw_<ts>.md.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
BIN="$ROOT/build/bin/nr_bench"
UDS="${UDS:-/tmp/native_rdma-dp.sock}"
DUR="${DUR:-15}"
TS="$(date +%Y%m%d_%H%M%S)"
OUT="$ROOT/logs/bench_bw_${TS}.md"
mkdir -p "$ROOT/logs"

if [ ! -x "$BIN" ]; then
    echo "nr_bench not found: $BIN"
    echo "Build with:  cmake --build build -j"
    exit 1
fi
if [ ! -S "$UDS" ]; then
    echo "UDS socket not present: $UDS ; is native_rdma_dp running?"
    exit 1
fi

# sample aggregate CPU utilization across all cores during a run
cpu_util_sample() {
    local secs=$1
    awk -v secs="$secs" '
        BEGIN { getline line < "/proc/stat"; split(line,a); }
        END {
            for (i=2; i<=8; i++) t1 += a[i];
            b1 = a[5];  # idle
            cmd = "sleep " secs
            system(cmd)
            getline line2 < "/proc/stat"; split(line2,b);
            for (i=2; i<=8; i++) t2 += b[i];
            b2 = b[5];
            dt = t2 - t1; di = b2 - b1;
            if (dt <= 0) { printf "0.0"; exit }
            printf "%.1f", (1 - di/dt) * 100;
        }'
}

{
echo "# W4 Bandwidth Bench"
echo
echo "- Time       : $(date -Iseconds)"
echo "- Host       : $(hostname)"
echo "- Duration/ea: ${DUR}s"
echo "- UDS        : \`$UDS\`"
echo
echo "| threads | val_size | ops/s | MB/s | Gbps | avg us | p50 us | p99 us | max us |"
echo "|---------|----------|-------|------|------|--------|--------|--------|--------|"
} > "$OUT"

run_case() {
    local th=$1 sz=$2
    echo ">>> threads=$th val_size=$sz" >&2
    local tmp
    tmp=$("$BIN" --uds="$UDS" --op=put --threads="$th" \
                 --val-size="$sz" --duration="$DUR" 2>&1)
    echo "$tmp" >&2
    local ops avg p50 p99 mx
    ops=$(echo "$tmp" | awk '/ops\/s/ {print $NF}')
    avg=$(echo "$tmp" | awk '/latency us/ {for(i=1;i<=NF;i++) if($i ~ /^avg=/)  print substr($i,5)}')
    p50=$(echo "$tmp" | awk '/latency us/ {for(i=1;i<=NF;i++) if($i ~ /^p50=/)  print substr($i,5)}')
    p99=$(echo "$tmp" | awk '/latency us/ {for(i=1;i<=NF;i++) if($i ~ /^p99=/)  print substr($i,5)}')
    mx=$( echo "$tmp" | awk '/latency us/ {for(i=1;i<=NF;i++) if($i ~ /^max=/)  print substr($i,5)}')
    # MB/s = ops/s * val_size / 1e6
    local mbs gbps
    mbs=$(awk -v o="$ops" -v s="$sz" 'BEGIN{printf "%.1f", o*s/1e6}')
    gbps=$(awk -v o="$ops" -v s="$sz" 'BEGIN{printf "%.2f", o*s*8/1e9}')
    echo "| $th | $sz | $ops | $mbs | $gbps | $avg | $p50 | $p99 | $mx |" >> "$OUT"
}

# Bandwidth sweep.
# NOTE: slab slot_size limits max val_size. If you want to test 64KB+ payloads,
#   RESTART the data plane with:
#     SLAB_SLOT_SIZE=1048576 SLAB_TOTAL_BYTES=$((4<<30)) \
#       bash scripts/start_node.sh --role=A
#   (4GB slab with 1MB slots accommodates up to 1MB values.)
#
# Default path (1 KB slot, tests small/medium concurrency):
run_case 1  1024
run_case 4  1024
run_case 8  1024
run_case 16 1024
run_case 32 1024

# Large object path (only runs if slab slot was raised; otherwise nr_bench
# will return value-too-large for these sizes which shows up as fail count).
if [ "${TEST_LARGE:-0}" = "1" ]; then
    run_case 2  65536     # 64 KB
    run_case 4  65536
    run_case 2  262144    # 256 KB
    run_case 4  262144
    run_case 1  1048576   # 1 MB
    run_case 2  1048576
fi

echo >> "$OUT"
echo "Notes:" >> "$OUT"
echo "- Each PUT performs a signaled RDMA WRITE to the peer slab at matching offset." >> "$OUT"
echo "- Bandwidth is end-to-end from the nr_bench client through UDS + data-plane + RDMA WRITE + CQ poll, not an ib_write_bw style loopback." >> "$OUT"
echo "- To go beyond 1 KB per op, raise SlabPool slot_size in main.cpp (currently 1024)." >> "$OUT"

echo
echo "[done] report: $OUT"
cat "$OUT"
