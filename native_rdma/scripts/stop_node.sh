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
#
# IMPORTANT: match on 'build/bin/native_rdma_dp' (the full executable path
# fragment) instead of bare 'native_rdma_dp'. When this script is invoked
# via `ssh host "pkill -f native_rdma_dp"`, the remote login shell's own
# command line contains the literal string "native_rdma_dp" and pkill would
# happily kill itself, severing the session before it actually gets to the
# real DP process. Using the build path fragment avoids the self-match.
set -u
MATCH='build/bin/native_rdma_dp'
pkill -TERM -f "$MATCH" 2>/dev/null || true
for _ in 1 2 3 4 5; do
    pgrep -f "$MATCH" >/dev/null || break
    sleep 0.5
done
pkill -KILL -f "$MATCH" 2>/dev/null || true
for _ in 1 2 3 4 5; do
    pgrep -f "$MATCH" >/dev/null || break
    sleep 0.5
done

# Clean ipc artifacts so the control plane does not serve a ghost snapshot.
rm -f /tmp/native_rdma-dp.sock /tmp/native_rdma-metrics.shm 2>/dev/null || true

# Sanity check: report any leftover PIDs so the caller can tell.
leftover=$(pgrep -af "$MATCH" || true)
if [ -n "$leftover" ]; then
    echo "[stop_node] WARNING: DP processes still running after KILL:"
    echo "$leftover"
    exit 1
fi
echo "[stop_node] done (cleaned /tmp/native_rdma-dp.sock and metrics shm)"
