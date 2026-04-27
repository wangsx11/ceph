#!/usr/bin/env bash
# Perf #9: Memory pool overhead / savings / scaling.
# Drives the standalone nr_mempool_bench binary and passes its JSON through
# to logs/perf/.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
BIN="$ROOT/build/bin/nr_mempool_bench"
THREADS="${THREADS:-8}"
OUT_DIR="${OUT_DIR:-$ROOT/logs/perf}"
TS="$(date +%Y%m%d_%H%M%S)"
mkdir -p "$OUT_DIR"
OUT="$OUT_DIR/perf_09_mempool_${TS}.json"

[ -x "$BIN" ] || { echo "nr_mempool_bench missing -- cmake --build build -j" >&2; exit 2; }

echo ">>> perf#9 mempool bench threads=$THREADS" >&2
"$BIN" --threads="$THREADS" | tee "$OUT"
echo "[done] $OUT"
