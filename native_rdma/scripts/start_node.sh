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

BUILD_DIR="${NR_BUILD_DIR:-$ROOT/build-current}"
BIN="$BUILD_DIR/bin/native_rdma_dp"
if [ ! -x "$BIN" ] && [ -x "$ROOT/build/bin/native_rdma_dp" ]; then
    BUILD_DIR="$ROOT/build"
    BIN="$BUILD_DIR/bin/native_rdma_dp"
fi
[ -x "$BIN" ] || { echo "binary not built: $BIN (run: cmake -S . -B \"$BUILD_DIR\" && cmake --build \"$BUILD_DIR\" -j)"; exit 1; }

LOG_DIR="$ROOT/logs"
mkdir -p "$LOG_DIR"

# Best-effort cleanup of stale IPC artifacts left behind by a previous run
# that was killed hard. Without this, UdsServer may fail to bind and Flask
# will keep reading the last snapshot from the metrics shm file.
if [ -e "${UDS_PATH:-/tmp/native_rdma-dp.sock}" ] && \
   ! pgrep -f 'native_rdma_dp' >/dev/null 2>&1; then
    echo "[start_node] cleaning stale ${UDS_PATH} and ${METRICS_SHM}"
    rm -f "${UDS_PATH:-/tmp/native_rdma-dp.sock}" \
          "${METRICS_SHM:-/tmp/native_rdma-metrics.shm}" || true
fi

echo "[start_node] role=$ROLE self=$SELF_IP peer=$PEER_IP dev=$RDMA_DEV gid=$GID_IDX build=$BUILD_DIR"

exec "$BIN" \
    --role="$ROLE" \
    --self-ip="$SELF_IP" \
    --peer-ip="$PEER_IP" \
    --dev="$RDMA_DEV" \
    --gid-idx="$GID_IDX" \
    --data-port="$DATA_PORT" \
    --uds="$UDS_PATH" \
    --metrics-shm="$METRICS_SHM" \
    --slab-slot-size="${SLAB_SLOT_SIZE:-1024}" \
    --slab-total-bytes="${SLAB_TOTAL_BYTES:-1073741824}" \
    --nvme-path="${NVME_PATH:-/dev/shm/native_rdma_warm}" \
    --hdd-path="${HDD_PATH:-/dev/shm/native_rdma_cold}" \
    --demote-hot-score="${DEMOTE_HOT_SCORE:-0.30}" \
    --demote-warm-score="${DEMOTE_WARM_SCORE:-0.05}" \
    --time-decay-alpha="${TIME_DECAY_ALPHA:-0.10}" \
    --heat-score-init="${HEAT_SCORE_INIT:-1.0}" \
    --score-grace-ms="${SCORE_GRACE_MS:-2000}" \
    --migrate-interval-ms="${MIGRATE_INTERVAL_MS:-1000}" \
    --migrate-batch-limit="${MIGRATE_BATCH_LIMIT:-16}" \
    --async-repl="${NR_ASYNC_REPL:-0}" \
    2>&1 | tee -a "$LOG_DIR/dp_${ROLE}.log"
