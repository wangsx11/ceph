#!/usr/bin/env bash
# Sync source tree to the peer node via rsync over ssh.
# Usage: bash scripts/sync_to_peer.sh <NODE_B_IP>
set -euo pipefail

PEER="${1:-}"
[ -z "$PEER" ] && { echo "usage: $0 <peer_ip_or_host>"; exit 1; }

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
REMOTE_PATH="${REMOTE_PATH:-$ROOT}"

rsync -avz --delete \
    --exclude 'build/' \
    --exclude 'logs/' \
    --exclude '__pycache__/' \
    --exclude '*.pyc' \
    --exclude '.git/' \
    "$ROOT/" "$PEER:$REMOTE_PATH/"

echo "[sync_to_peer] synced to $PEER:$REMOTE_PATH"
