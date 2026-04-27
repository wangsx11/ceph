#!/usr/bin/env bash
# Install build / runtime dependencies for native_rdma on Ubuntu 20.04 / 22.04.
# Safe to re-run; uses apt-get install which is idempotent.
set -euo pipefail

SUDO=$( [ "$EUID" -eq 0 ] || command -v sudo >/dev/null && echo sudo || echo "" )

$SUDO apt-get update
$SUDO apt-get install -y \
    build-essential cmake ninja-build pkg-config git \
    libibverbs-dev librdmacm-dev libibverbs1 librdmacm1 ibverbs-utils perftest \
    libzstd-dev liblz4-dev libssl-dev \
    libprotobuf-dev protobuf-compiler \
    python3 python3-pip python3-venv

# xxhash is not available on every distro; tolerate failure.
$SUDO apt-get install -y libxxhash-dev || true

# liburing: Ubuntu 20.04 focal does not ship a recent enough version (or none at all).
# Try apt first; if not available or version < 2.0, build from source.
need_build_liburing=0
if ! $SUDO apt-get install -y liburing-dev 2>/dev/null; then
    echo "[install_deps] liburing-dev not available via apt, will build from source"
    need_build_liburing=1
else
    ver=$(pkg-config --modversion liburing 2>/dev/null || echo "0")
    major=${ver%%.*}
    if [ "${major:-0}" -lt 2 ]; then
        echo "[install_deps] liburing version $ver too old, will build from source"
        need_build_liburing=1
    fi
fi

if [ "$need_build_liburing" -eq 1 ]; then
    tmpdir=$(mktemp -d)
    trap 'rm -rf "$tmpdir"' EXIT
    git clone --depth 1 --branch liburing-2.5 https://github.com/axboe/liburing.git "$tmpdir/liburing"
    pushd "$tmpdir/liburing" >/dev/null
    ./configure --prefix=/usr
    make -j"$(nproc)"
    $SUDO make install
    $SUDO ldconfig
    popd >/dev/null
    echo "[install_deps] liburing $(pkg-config --modversion liburing) installed from source"
fi

pip3 install --user --upgrade pip
pip3 install --user flask flask-cors flask-sock protobuf psutil requests

echo "[install_deps] done"
