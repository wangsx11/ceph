#!/usr/bin/env bash
# Start a native_rdma node.
# Usage: bash scripts/start_node.sh --role=A
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ROLE=""
for a in "$@"; do
    case $a in
        --role=*) ROLE="${a#*=}" ;;
    esac
done
[ -z "$ROLE" ] && { echo "missing --role=A|B"; exit 1; }

ENV_FILE="$ROOT/deploy/node_${ROLE,,}.env"
[ -f "$ENV_FILE" ] || { echo "no env file: $ENV_FILE"; exit 1; }
# shellcheck disable=SC1090
source "$ENV_FILE"

BIN="$ROOT/build/bin/native_rdma_dp"
[ -x "$BIN" ] || { echo "binary not built: $BIN (run: cmake -S . -B build && cmake --build build -j)"; exit 1; }

LOG_DIR="$ROOT/logs"
mkdir -p "$LOG_DIR"

echo "[start_node] role=$ROLE self=$SELF_IP peer=$PEER_IP dev=$RDMA_DEV gid=$GID_IDX"

exec "$BIN" \
    --role="$ROLE" \
    --self-ip="$SELF_IP" \
    --peer-ip="$PEER_IP" \
    --dev="$RDMA_DEV" \
    --gid-idx="$GID_IDX" \
    --data-port="$DATA_PORT" \
    --uds="$UDS_PATH" \
    --metrics-shm="$METRICS_SHM" \
    2>&1 | tee -a "$LOG_DIR/dp_${ROLE}.log"
