#!/usr/bin/env bash
# Stop running native_rdma_dp process and clean stale UDS/shm artifacts.
# Without cleanup, the metrics shm file keeps the last snapshot on disk and
# causes the Flask control plane to report "offline+ops=54k" simultaneously
# after a crash/kill. So we unlink both here.
set -euo pipefail
pkill -TERM -f 'native_rdma_dp' || true
sleep 1
pkill -KILL -f 'native_rdma_dp' || true
# Clean ipc artifacts so the control plane does not serve a ghost snapshot.
rm -f /tmp/native_rdma-dp.sock /tmp/native_rdma-metrics.shm || true
echo "[stop_node] done (cleaned /tmp/native_rdma-dp.sock and metrics shm)"
