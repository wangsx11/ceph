#!/usr/bin/env bash
# Stop the native_rdma demo stack on node A and node B.
#
# Usage:
#   bash stop.sh
#
# Optional environment variables:
#   PEER_HOST=xfusion4
#   PEER_ROOT=~/ceph-web/native_rdma
#   STOP_PEER=1

set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PEER_HOST="${PEER_HOST:-xfusion4}"
PEER_ROOT="${PEER_ROOT:-~/ceph-web/native_rdma}"
STOP_PEER="${STOP_PEER:-1}"
RC=0

say() {
    printf '[stop] %s\n' "$*"
}

warn() {
    printf '[stop][WARN] %s\n' "$*" >&2
}

stop_local() {
    say "stopping local stack: $ROOT"
    if bash "$ROOT/scripts/demo_down.sh"; then
        say "local stack stopped"
    else
        warn "local stop failed"
        RC=1
    fi
}

stop_peer() {
    if [ "$STOP_PEER" = "0" ]; then
        say "skip peer stop because STOP_PEER=0"
        return
    fi

    say "stopping peer stack: ${PEER_HOST}:${PEER_ROOT}"
    if ssh "$PEER_HOST" "cd $PEER_ROOT && bash scripts/demo_down.sh"; then
        say "peer stack stopped"
    else
        warn "peer stop failed: ${PEER_HOST}:${PEER_ROOT}"
        RC=1
    fi
}

stop_local
stop_peer

if [ "$RC" -eq 0 ]; then
    say "all requested stacks stopped"
else
    warn "finished with errors"
fi

exit "$RC"
