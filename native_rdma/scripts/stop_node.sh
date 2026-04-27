#!/usr/bin/env bash
# Stop running native_rdma_dp process.
set -euo pipefail
pkill -TERM -f 'native_rdma_dp' || true
sleep 1
pkill -KILL -f 'native_rdma_dp' || true
echo "[stop_node] done"
