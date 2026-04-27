#!/usr/bin/env bash
# ============================================================
# backend_v2 setup_pools.sh — initialise pools + ramfs + tune
# ============================================================
set -e

have_pool() { rados lspools 2>/dev/null | grep -qw "$1"; }

create_pool() {
    local name=$1 pg=${2:-64} rep=${3:-2}
    if have_pool "$name"; then
        echo "  ✓ $name exists"
    else
        ceph osd pool create "$name" "$pg" "$pg"
        ceph osd pool set "$name" size "$rep"
        ceph osd pool application enable "$name" rados --yes-i-really-mean-it >/dev/null
        echo "  + $name (pg=$pg, rep=$rep)"
    fi
}

echo "[1/5] creating pools …"
create_pool sync_pool   64
create_pool perf_pool  256
create_pool warm_pool  128
create_pool cold_pool  128
create_pool backup_pool 32
create_pool mempool_pool 64

echo "[2/5] compression / priority tuning …"
ceph osd pool set warm_pool compression_mode aggressive || true
ceph osd pool set warm_pool compression_algorithm zstd  || true
ceph osd pool set perf_pool recovery_priority 1         || true

echo "[3/5] mounting DRAM hot tier /mnt/hot …"
sudo mkdir -p /mnt/hot
if ! mountpoint -q /mnt/hot; then
    sudo mount -t ramfs ramfs /mnt/hot
    sudo chmod 777 /mnt/hot
fi

echo "[4/5] python deps …"
pip3 install flask flask-cors --break-system-packages 2>/dev/null \
  || pip3 install flask flask-cors 2>/dev/null || true

echo "[5/5] quick health …"
ceph -s | head -20
echo "done."
