#!/usr/bin/env bash
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"
for t in test_*.py; do
    echo "========== $t =========="
    python3 "$t" || exit $?
done
echo "[DONE] rdma_distributed all PASS"
