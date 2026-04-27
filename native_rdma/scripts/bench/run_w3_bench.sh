#!/usr/bin/env bash
# W3 bench matrix: multiple shapes of PUT / GET / MIX via nr_bench (UDS direct).
# Writes a Markdown report to logs/bench_w3_<ts>.md
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
BIN="$ROOT/build/bin/nr_bench"
UDS="${UDS:-/tmp/native_rdma-dp.sock}"
DUR="${DUR:-10}"
TS="$(date +%Y%m%d_%H%M%S)"
OUT="$ROOT/logs/bench_w3_${TS}.md"
mkdir -p "$ROOT/logs"

if [ ! -x "$BIN" ]; then
    echo "nr_bench not found: $BIN"
    echo "Build with:  cmake --build build -j"
    exit 1
fi
if [ ! -S "$UDS" ]; then
    echo "UDS socket not present: $UDS"
    echo "Is native_rdma_dp running?"
    exit 1
fi

{
echo "# W3 Benchmark Report"
echo
echo "- Time        : $(date -Iseconds)"
echo "- UDS         : \`$UDS\`"
echo "- Duration/ea : ${DUR}s"
echo "- Host        : $(hostname)"
echo
echo "| op | threads | val_size | ops/s | avg us | p50 us | p99 us | p99.9 us | max us |"
echo "|----|---------|----------|-------|--------|--------|--------|----------|--------|"
} > "$OUT"

run_case() {
    local op=$1 th=$2 sz=$3
    echo ">>> op=$op threads=$th val_size=$sz" >&2
    local tmp
    tmp=$("$BIN" --uds="$UDS" --op="$op" --threads="$th" \
                 --val-size="$sz" --duration="$DUR" 2>&1)
    echo "$tmp" >&2
    # Parse key lines
    local ops avg p50 p99 p999 mx
    ops=$( echo "$tmp" | awk '/ops\/s/         {print $NF}')
    avg=$( echo "$tmp" | awk '/latency us/     {for(i=1;i<=NF;i++) if($i ~ /^avg=/)  print substr($i,5)}')
    p50=$( echo "$tmp" | awk '/latency us/     {for(i=1;i<=NF;i++) if($i ~ /^p50=/)  print substr($i,5)}')
    p99=$( echo "$tmp" | awk '/latency us/     {for(i=1;i<=NF;i++) if($i ~ /^p99=/)  print substr($i,5)}')
    p999=$(echo "$tmp" | awk '/latency us/     {for(i=1;i<=NF;i++) if($i ~ /^p99\.9=/) print substr($i,7)}')
    mx=$(  echo "$tmp" | awk '/latency us/     {for(i=1;i<=NF;i++) if($i ~ /^max=/)  print substr($i,5)}')
    echo "| $op | $th | $sz | $ops | $avg | $p50 | $p99 | $p999 | $mx |" >> "$OUT"
}

# ---- sweep ----
# small PUT latency: single-thread baseline
run_case put 1  64
run_case put 1 256
run_case put 1 1024
# PUT throughput
run_case put 4  64
run_case put 8  64
run_case put 16 64
# GET latency (local hit)
run_case get 1  64
run_case get 8  64
# mixed workload
run_case mix 8  256

echo >> "$OUT"
echo "Raw log in bench_http can be run from host: \`python3 scripts/bench/bench_http.py ...\`" >> "$OUT"

echo
echo "[done] report: $OUT"
cat "$OUT"
