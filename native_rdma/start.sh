#!/usr/bin/env bash
# Start the two-node native_rdma demo stack from the current checkout.
#
# Optional env:
#   PEER_HOST=xfusion4
#   PEER_REPO_ROOT=/home/wangshouxin/native-rdma-web
#   NR_BUILD_DIR=/path/to/build-current
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${ROOT}/.." && pwd)"
REPO_NAME="$(basename "${REPO_ROOT}")"

PEER_HOST="${PEER_HOST:-xfusion4}"
PEER_REPO_ROOT="${PEER_REPO_ROOT:-/home/${USER}/${REPO_NAME}}"
PEER_NATIVE_ROOT="${PEER_REPO_ROOT}/native_rdma"
NR_BUILD_DIR="${NR_BUILD_DIR:-${ROOT}/build-current}"

export NR_BUILD_DIR
export NR_ASYNC_REPL="${NR_ASYNC_REPL:-1}"

say() { printf '[start] %s\n' "$*"; }

say "repo=${REPO_ROOT}"
say "build=${NR_BUILD_DIR}"
say "peer=${PEER_HOST}:${PEER_REPO_ROOT}"

say "build local"
cmake -S "${ROOT}" -B "${NR_BUILD_DIR}" -DCMAKE_BUILD_TYPE=Release -GNinja
cmake --build "${NR_BUILD_DIR}" -j

say "check peer ssh"
ssh "${PEER_HOST}" "hostname >/dev/null"

say "sync repo to peer"
ssh "${PEER_HOST}" "mkdir -p '${PEER_REPO_ROOT}'"
rsync -avz \
    --exclude 'native_rdma/build/' \
    --exclude 'native_rdma/build-current/' \
    --exclude 'native_rdma/logs/' \
    --exclude '__pycache__/' \
    --exclude '*.pyc' \
    "${REPO_ROOT}/" "${PEER_HOST}:${PEER_REPO_ROOT}/"

say "build peer"
ssh "${PEER_HOST}" \
    "cd '${PEER_NATIVE_ROOT}' && cmake -S . -B build-current -DCMAKE_BUILD_TYPE=Release -GNinja && cmake --build build-current -j"

say "clean cold-tier leftovers"
rm -rf /home/wangshouxin/nr_cold/* 2>/dev/null || true
ssh "${PEER_HOST}" "rm -rf /tmp/nr_cold/* 2>/dev/null || true" || true

say "stop old local stack"
bash "${ROOT}/scripts/demo_down.sh" 2>/dev/null || true

say "stop old peer stack"
ssh "${PEER_HOST}" "cd '${PEER_NATIVE_ROOT}' && bash scripts/demo_down.sh" 2>/dev/null || true

say "start peer role B"
ssh "${PEER_HOST}" "cd '${PEER_NATIVE_ROOT}' && NR_BUILD_DIR='${PEER_NATIVE_ROOT}/build-current' NR_ASYNC_REPL='${NR_ASYNC_REPL}' ROLE=B bash scripts/demo_up.sh"
sleep 3

say "start local role A"
ROLE=A NR_BUILD_DIR="${NR_BUILD_DIR}" NR_ASYNC_REPL="${NR_ASYNC_REPL}" bash "${ROOT}/scripts/demo_up.sh"
