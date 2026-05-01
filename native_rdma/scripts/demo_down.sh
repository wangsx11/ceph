#!/usr/bin/env bash
# demo_down.sh — 停止本端的 Data Plane + Flask
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "[demo_down] 精确匹配 $ROOT/build/bin/native_rdma_dp ..."
pkill -9 -f "$ROOT/build/bin/native_rdma_dp" 2>/dev/null || true
pkill -f  "python3 $ROOT/control_plane/app.py" 2>/dev/null || true
rm -f /tmp/native_rdma-dp.sock /tmp/native_rdma-metrics.shm
echo "[demo_down] 已清理"
