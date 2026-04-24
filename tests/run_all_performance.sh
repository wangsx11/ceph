#!/usr/bin/env bash
# 依次跑全部性能测试，最后用 summary.py 汇总
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE/performance"

for f in baseline/*.py stress/*.py rdma_network/test_*.py; do
    echo "========== $f =========="
    python3 "$f" || echo "[WARN] $f reported failure"
done

echo ""
echo "==================== SUMMARY ===================="
python3 summary.py
