#!/usr/bin/env bash
# OS tuning for native_rdma. Run with sudo on BOTH nodes.
# See docs/自研方案.md §7.1 for rationale.
set -euo pipefail

if [ "$EUID" -ne 0 ]; then
    echo "Please run as root (use sudo)." >&2
    exit 1
fi

# --- 1. HugePages (override via env: HUGEPAGES_2MB) -------------------
HUGEPAGES_2MB="${HUGEPAGES_2MB:-16384}"    # default 32GB
echo "[tune_os] setting HugePages to ${HUGEPAGES_2MB} x 2MB"
echo "$HUGEPAGES_2MB" > /proc/sys/vm/nr_hugepages

sysctl -w vm.swappiness=1
sysctl -w vm.zone_reclaim_mode=0

# --- 2. CPU performance mode ----------------------------------------
if command -v cpupower >/dev/null; then
    cpupower frequency-set -g performance || true
fi
for c in /sys/devices/system/cpu/cpu*/cpuidle/state*/disable; do
    [ -w "$c" ] && echo 1 > "$c" || true
done

# --- 3. IRQ affinity ------------------------------------------------
systemctl stop  irqbalance 2>/dev/null || true
systemctl disable irqbalance 2>/dev/null || true
echo "[tune_os] NOTE: manually pin mlx5 IRQs to HCA's NUMA node if needed."

# --- 4. Memlock unlimited -------------------------------------------
if ! grep -q "memlock unlimited" /etc/security/limits.conf; then
    cat >> /etc/security/limits.conf <<EOF
* soft memlock unlimited
* hard memlock unlimited
* soft nofile 1048576
* hard nofile 1048576
EOF
    echo "[tune_os] memlock/nofile limits added."
fi

echo "[tune_os] done. Re-login or reboot for limits to take effect."
