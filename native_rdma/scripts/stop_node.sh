#!/usr/bin/env bash
# Stop running native_rdma_dp process and clean stale UDS/shm artifacts.
# Without cleanup, the metrics shm file keeps the last snapshot on disk and
# causes the Flask control plane to report "offline+ops=54k" simultaneously
# after a crash/kill. So we unlink both here.
#
# We also retry KILL with a bounded wait so ssh-driven invocations don't
# silently leave a zombie DP running (observed during W5: stop_node reported
# success over ssh but `pgrep` later still returned the old PID because the
# first SIGTERM arrived during post_send and was ignored).
set -u
pkill -TERM -f 'native_rdma_dp' 2>/dev/null || true
for _ in 1 2 3 4 5; do
    pgrep -f 'native_rdma_dp' >/dev/null || break
    sleep 0.5
done
pkill -KILL -f 'native_rdma_dp' 2>/dev/null || true
for _ in 1 2 3 4 5; do
    pgrep -f 'native_rdma_dp' >/dev/null || break
    sleep 0.5
done

# Clean ipc artifacts so the control plane does not serve a ghost snapshot.
rm -f /tmp/native_rdma-dp.sock /tmp/native_rdma-metrics.shm 2>/dev/null || true

# Sanity check: report any leftover PIDs so the caller can tell.
leftover=$(pgrep -af 'native_rdma_dp' || true)
if [ -n "$leftover" ]; then
    echo "[stop_node] WARNING: DP processes still running after KILL:"
    echo "$leftover"
    exit 1
fi
echo "[stop_node] done (cleaned /tmp/native_rdma-dp.sock and metrics shm)"
