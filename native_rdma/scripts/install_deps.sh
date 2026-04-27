#!/usr/bin/env bash
# Install build / runtime dependencies for native_rdma on Ubuntu 20.04 / 22.04.
# Safe to re-run; uses apt-get install which is idempotent.
set -euo pipefail

SUDO=$( [ "$EUID" -eq 0 ] || command -v sudo >/dev/null && echo sudo || echo "" )

$SUDO apt-get update
$SUDO apt-get install -y \
    build-essential cmake ninja-build pkg-config git \
    libibverbs-dev librdmacm-dev libibverbs1 librdmacm1 ibverbs-utils perftest \
    liburing-dev libzstd-dev liblz4-dev libssl-dev \
    libprotobuf-dev protobuf-compiler \
    python3 python3-pip python3-venv

# xxhash is not available on every distro; tolerate failure.
$SUDO apt-get install -y libxxhash-dev || true

pip3 install --user --upgrade pip
pip3 install --user flask flask-cors flask-sock protobuf psutil requests

echo "[install_deps] done"
