#!/usr/bin/env bash
# Start the two-node native_rdma demo stack from the current checkout.
#
# Optional env:
#   PEER_HOST=xfusion4
#   LOCAL_HOST=xfusion3   # optional: start role A through ssh as well
#   PEER_REPO_ROOT=/home/wangshouxin/native-rdma-web
#   NR_BUILD_DIR=/path/to/build-current
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${ROOT}/.." && pwd)"
REPO_NAME="$(basename "${REPO_ROOT}")"

PEER_HOST="${PEER_HOST:-xfusion4}"
LOCAL_HOST="${LOCAL_HOST:-}"
PEER_REPO_ROOT="${PEER_REPO_ROOT:-/home/${USER}/${REPO_NAME}}"
PEER_NATIVE_ROOT="${PEER_REPO_ROOT}/native_rdma"
NR_BUILD_DIR="${NR_BUILD_DIR:-${ROOT}/build-current}"

export NR_BUILD_DIR
# Functional validation defaults to synchronous RDMA replication so scripts can
# read back peer state immediately. Performance runs can override with
# NR_ASYNC_REPL=1.
export NR_ASYNC_REPL="${NR_ASYNC_REPL:-0}"
export NR_TRANSPORT="${NR_TRANSPORT:-rdma}"
export NR_TCP_DATA_PORT="${NR_TCP_DATA_PORT:-18516}"
export NR_RDMA_TRAFFIC_CLASS="${NR_RDMA_TRAFFIC_CLASS:-0}"
export NR_GDR_ENABLE="${NR_GDR_ENABLE:-0}"
export NR_CUDA_DEVICE="${NR_CUDA_DEVICE:-0}"
export NR_GDR_BYTES="${NR_GDR_BYTES:-67108864}"
export NR_SKIP_FLASK="${NR_SKIP_FLASK:-0}"

REMOTE_EXTRA_ENV=""
LOCAL_EXTRA_ENV=()
add_optional_env() {
    local name="$1"
    local value="${!name:-}"
    if [ -n "$value" ]; then
        REMOTE_EXTRA_ENV+=" ${name}='${value}'"
        LOCAL_EXTRA_ENV+=("${name}=${value}")
    fi
}

for optional_name in \
    SLAB_SLOT_SIZE \
    SLAB_TOTAL_BYTES \
    NR_LO_RATE_KOPS \
    NR_QOS_HI_WINDOW_US \
    NR_QOS_LO_BURST_MS \
    NR_RDMA_TRAFFIC_CLASS
do
    add_optional_env "${optional_name}"
done

LOCAL_CUDA_FLAG="-DNR_USE_CUDA=OFF"
PEER_CUDA_FLAG="-DNR_USE_CUDA=OFF"
if [ "${NR_GDR_ENABLE}" = "1" ] || [ "${NR_GDR_ENABLE}" = "true" ]; then
    PEER_CUDA_FLAG="-DNR_USE_CUDA=ON -DCMAKE_CUDA_COMPILER=/usr/local/cuda/bin/nvcc"
fi

say() { printf '[start] %s\n' "$*"; }
SSH_OPTS=(-o ServerAliveInterval=15 -o ServerAliveCountMax=6 -o TCPKeepAlive=yes)

say "repo=${REPO_ROOT}"
say "build=${NR_BUILD_DIR}"
say "peer=${PEER_HOST}:${PEER_REPO_ROOT}"

say "build local"
cmake -S "${ROOT}" -B "${NR_BUILD_DIR}" -DCMAKE_BUILD_TYPE=Release "${LOCAL_CUDA_FLAG}" -GNinja
cmake --build "${NR_BUILD_DIR}" -j

say "check peer ssh"
ssh "${SSH_OPTS[@]}" "${PEER_HOST}" "hostname >/dev/null"

say "sync repo to peer"
ssh "${SSH_OPTS[@]}" "${PEER_HOST}" "mkdir -p '${PEER_REPO_ROOT}'"
rsync -avz \
    -e "ssh -o ServerAliveInterval=15 -o ServerAliveCountMax=6 -o TCPKeepAlive=yes" \
    --exclude 'native_rdma/build/' \
    --exclude 'native_rdma/build-current/' \
    --exclude 'native_rdma/logs/' \
    --exclude 'functions/history/' \
    --exclude 'functions/*/FN-*/history/' \
    --exclude 'performances/history/' \
    --exclude 'performances/PF-*/history/' \
    --exclude '__pycache__/' \
    --exclude '*.pyc' \
    "${REPO_ROOT}/" "${PEER_HOST}:${PEER_REPO_ROOT}/"

say "build peer"
ssh "${SSH_OPTS[@]}" "${PEER_HOST}" \
    "cd '${PEER_NATIVE_ROOT}' && cmake -S . -B build-current -DCMAKE_BUILD_TYPE=Release ${PEER_CUDA_FLAG} -GNinja && cmake --build build-current -j"

say "clean cold-tier leftovers"
rm -rf /home/wangshouxin/nr_cold/* 2>/dev/null || true
ssh "${SSH_OPTS[@]}" "${PEER_HOST}" "rm -rf /tmp/nr_cold/* 2>/dev/null || true" || true

say "stop old local stack"
NR_SKIP_FLASK="${NR_SKIP_FLASK}" bash "${ROOT}/scripts/demo_down.sh" 2>/dev/null || true

say "stop old peer stack"
ssh "${SSH_OPTS[@]}" "${PEER_HOST}" "cd '${PEER_NATIVE_ROOT}' && NR_SKIP_FLASK='${NR_SKIP_FLASK}' bash scripts/demo_down.sh" 2>/dev/null || true

say "start peer role B"
ssh "${SSH_OPTS[@]}" "${PEER_HOST}" "cd '${PEER_NATIVE_ROOT}' && NR_BUILD_DIR='${PEER_NATIVE_ROOT}/build-current' NR_ASYNC_REPL='${NR_ASYNC_REPL}' NR_TRANSPORT='${NR_TRANSPORT}' NR_TCP_DATA_PORT='${NR_TCP_DATA_PORT}' NR_GDR_ENABLE='${NR_GDR_ENABLE}' NR_CUDA_DEVICE='${NR_CUDA_DEVICE}' NR_GDR_BYTES='${NR_GDR_BYTES}' NR_SKIP_FLASK='${NR_SKIP_FLASK}'${REMOTE_EXTRA_ENV} ROLE=B bash scripts/demo_up.sh"
sleep 3

say "start local role A"
if [ -n "${LOCAL_HOST}" ]; then
    ssh "${SSH_OPTS[@]}" "${LOCAL_HOST}" "cd '${ROOT}' && ROLE=A NR_BUILD_DIR='${NR_BUILD_DIR}' NR_ASYNC_REPL='${NR_ASYNC_REPL}' NR_TRANSPORT='${NR_TRANSPORT}' NR_TCP_DATA_PORT='${NR_TCP_DATA_PORT}' NR_GDR_ENABLE='${NR_GDR_ENABLE}' NR_CUDA_DEVICE='${NR_CUDA_DEVICE}' NR_GDR_BYTES='${NR_GDR_BYTES}' NR_SKIP_FLASK='${NR_SKIP_FLASK}'${REMOTE_EXTRA_ENV} bash scripts/demo_up.sh"
else
    env "${LOCAL_EXTRA_ENV[@]}" ROLE=A NR_BUILD_DIR="${NR_BUILD_DIR}" NR_ASYNC_REPL="${NR_ASYNC_REPL}" NR_TRANSPORT="${NR_TRANSPORT}" NR_TCP_DATA_PORT="${NR_TCP_DATA_PORT}" NR_GDR_ENABLE="${NR_GDR_ENABLE}" NR_CUDA_DEVICE="${NR_CUDA_DEVICE}" NR_GDR_BYTES="${NR_GDR_BYTES}" NR_SKIP_FLASK="${NR_SKIP_FLASK}" bash "${ROOT}/scripts/demo_up.sh"
fi
