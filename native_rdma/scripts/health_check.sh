#!/usr/bin/env bash
# health_check.sh - Comprehensive diagnostics for the native_rdma data plane.
#
# Answers the question "is my running DP process actually the freshly-compiled
# binary, and do the new RPCs work?".
#
# Usage:   bash scripts/health_check.sh
# Exit 0 on all-green, non-zero if anything mismatches.
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BIN="$ROOT/build/bin/native_rdma_dp"

C_RED='\033[0;31m'; C_GREEN='\033[0;32m'; C_YEL='\033[0;33m'; C_RST='\033[0m'
ok()   { echo -e "${C_GREEN}[OK]${C_RST}   $*"; }
warn() { echo -e "${C_YEL}[WARN]${C_RST} $*"; }
fail() { echo -e "${C_RED}[FAIL]${C_RST} $*"; }

errors=0
echo "== native_rdma health check =="
echo "root=$ROOT"
echo

# 1. Running DP processes
pids=($(pgrep -f native_rdma_dp || true))
if [ ${#pids[@]} -eq 0 ]; then
    fail "no native_rdma_dp process running"
    errors=$((errors+1))
else
    ok "found ${#pids[@]} native_rdma_dp process(es): ${pids[*]}"
    for pid in "${pids[@]}"; do
        exe=$(readlink -f /proc/$pid/exe 2>/dev/null || echo "?")
        started=$(ps -p $pid -o lstart= 2>/dev/null | xargs || echo "?")
        echo "  pid=$pid  exe=$exe"
        echo "              started=$started"
        # Compare binary mtime vs process start time.
        if [ -x "$exe" ] && [ -x "$BIN" ]; then
            bin_ts=$(stat -c %Y "$BIN")
            exe_ts=$(stat -c %Y "$exe")
            # If the binary file is strictly newer than the one the process is
            # running, the user edited + rebuilt but did NOT restart.
            if [ "$bin_ts" -gt "$exe_ts" ]; then
                warn "  build/bin binary is newer than the running exe -- restart required"
                errors=$((errors+1))
            fi
        fi
    done
fi
echo

# 2. IPC files
for f in /tmp/native_rdma-dp.sock /tmp/native_rdma-metrics.shm; do
    if [ -e "$f" ]; then ok "ipc artifact present: $f"
    else fail "ipc artifact missing: $f"; errors=$((errors+1)); fi
done
echo

# 3. Flask control plane
if pgrep -f 'python3 app.py' >/dev/null; then
    ok "control_plane (app.py) running"
else
    warn "control_plane not running -- start it with: cd control_plane && nohup python3 app.py > ../logs/cp.stdout.log 2>&1 &"
fi
echo

# 4. Cluster status
cs=$(curl -s --max-time 3 http://localhost:5000/api/cluster/status 2>/dev/null || echo "{}")
dp_on=$(echo "$cs" | python3 -c 'import sys,json;print(json.loads(sys.stdin.read() or "{}").get("dp_online", False))' 2>/dev/null || echo "False")
peer=$(  echo "$cs" | python3 -c 'import sys,json;print(json.loads(sys.stdin.read() or "{}").get("peer_alive", False))' 2>/dev/null || echo "False")
echo "cluster_status: dp_online=$dp_on peer_alive=$peer"
[ "$dp_on" = "True" ] || { fail "dp_online=$dp_on"; errors=$((errors+1)); }
[ "$peer"  = "True" ] || { warn "peer_alive=$peer (B node may be down)"; }
echo

# 5. Exercise every new W4 RPC with a controlled payload and report back.
#    Big value (8 KB of 'A') -> strong compressibility, should trigger
#    CompressEngine::pick() and move stats off zero.
echo "-- probing new W4 RPCs --"
# Ensure slot_size is large enough for the compression probe.
big=$(python3 -c 'print("A"*8192)')
put_resp=$(curl -s -X POST http://localhost:5000/api/kv/put \
   -H 'Content-Type: application/json' \
   -d "{\"key\":\"hc_big_1\",\"val\":\"$big\"}")
echo "  PUT big 8KB -> $put_resp"
if echo "$put_resp" | grep -q '"ok":true'; then
    ok "  8KB PUT accepted (slab slot_size >= 8192)"
else
    fail "  8KB PUT rejected -- restart DP with SLAB_SLOT_SIZE=16384 (or larger) to test compression"
    errors=$((errors+1))
fi

# Sequential GETs to exercise prefetcher.
for i in 1 2 3 4 5 6; do
    curl -s -X POST http://localhost:5000/api/kv/put \
         -H 'Content-Type: application/json' \
         -d "{\"key\":\"hc_seq_$i\",\"val\":\"v$i\"}" >/dev/null
done
for i in 1 2 3 4 5 6; do
    curl -s "http://localhost:5000/api/kv/get?key=hc_seq_$i" >/dev/null
done
pf=$(curl -s "http://localhost:5000/api/prefetch/stats?key=hc_seq_6")
echo "  prefetch after 6 sequential GETs -> $pf"
pf_total=$(echo "$pf" | python3 -c 'import sys,json;print(json.loads(sys.stdin.read()).get("total",0))' 2>/dev/null || echo 0)
if [ "${pf_total:-0}" -ge 1 ]; then
    ok "  prefetcher counted $pf_total accesses -- RPC wired correctly"
else
    fail "  prefetcher total=$pf_total despite 6 GETs -- suggests the DP is from an older build"
    errors=$((errors+1))
fi

# Demote big key to HDD to exercise compression.
curl -s -X POST http://localhost:5000/api/tier/demote \
   -H 'Content-Type: application/json' \
   -d '{"key":"hc_big_1","tier":"hdd"}' >/dev/null
cs2=$(curl -s http://localhost:5000/api/compress/stats)
echo "  compress after 8KB demote -> $cs2"
cmp_n=$(echo "$cs2" | python3 -c 'import sys,json;print(json.loads(sys.stdin.read()).get("objects",0))' 2>/dev/null || echo 0)
if [ "${cmp_n:-0}" -ge 1 ]; then
    ok "  compression engaged on HDD demote ($cmp_n object(s))"
else
    if echo "$put_resp" | grep -q '"ok":true'; then
        warn "  8KB went through but compress objects=$cmp_n -- DP likely pre-compression build"
        errors=$((errors+1))
    fi
fi

echo
if [ $errors -eq 0 ]; then
    ok "ALL CHECKS PASSED"
else
    fail "$errors check(s) failed"
fi
exit $errors
