#!/usr/bin/env bash
# Sync source tree to the peer node via rsync over ssh.
# Usage: bash scripts/sync_to_peer.sh <NODE_B_IP> [--with-binary]
#
# By default we only sync source code and let the peer re-build. The peer
# MUST run `cmake --build build -j` before starting DP. If you just want to
# push the already-compiled binary (same libc/glibc on both hosts), use the
# --with-binary flag or set WITH_BINARY=1, which additionally rsyncs
# build/bin/*. Note: this still does NOT push any build/ CMake cache, so the
# peer must have run cmake configure at least once.
set -euo pipefail

PEER=""
WITH_BINARY="${WITH_BINARY:-0}"
for arg in "$@"; do
    case "$arg" in
        --with-binary) WITH_BINARY=1 ;;
        -*)            echo "unknown flag: $arg" >&2; exit 1 ;;
        *)             PEER="$arg" ;;
    esac
done
[ -z "$PEER" ] && { echo "usage: $0 <peer_ip_or_host> [--with-binary]"; exit 1; }

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
REMOTE_PATH="${REMOTE_PATH:-$ROOT}"

echo "[sync_to_peer] syncing source to $PEER:$REMOTE_PATH"
rsync -avz --delete \
    --exclude 'build/' \
    --exclude 'logs/' \
    --exclude '__pycache__/' \
    --exclude '*.pyc' \
    --exclude '.git/' \
    "$ROOT/" "$PEER:$REMOTE_PATH/"

if [ "$WITH_BINARY" = "1" ]; then
    echo "[sync_to_peer] also pushing build/bin/* (WITH_BINARY=1)"
    ssh "$PEER" "mkdir -p $REMOTE_PATH/build/bin"
    # -c forces checksum comparison; -t preserves mtime so health_check's
    # mtime check can tell whether the peer DP matches.
    rsync -avzc \
        "$ROOT/build/bin/" "$PEER:$REMOTE_PATH/build/bin/"
fi

echo "[sync_to_peer] synced to $PEER:$REMOTE_PATH"
if [ "$WITH_BINARY" != "1" ]; then
    echo "[sync_to_peer] NOTE: build/ was NOT synced. Remember to run"
    echo "               'ssh $PEER \"cd $REMOTE_PATH && cmake --build build -j\"'"
    echo "               or re-run this script with --with-binary."
fi
