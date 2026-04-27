#!/bin/bash
# ============================================================
# setup_pools.sh — 初始化Ceph存储池和ramfs热层
# 在Ceph集群的任一节点上执行
# ============================================================

set -e

echo "=========================================="
echo "  分布式存储系统 - 初始化Ceph环境"
echo "=========================================="

# 获取已有Pool列表
EXISTING_POOLS=$(rados lspools 2>/dev/null || echo "")

create_pool_if_not_exists() {
  local pool_name=$1
  local pg_num=$2
  local replica_size=$3

  if echo "$EXISTING_POOLS" | grep -qw "$pool_name"; then
    echo "  ✓ $pool_name 已存在，跳过创建"
  else
    echo "  → 创建 $pool_name (pg=$pg_num, size=$replica_size)"
    ceph osd pool create "$pool_name" "$pg_num" "$pg_num"
    ceph osd pool set "$pool_name" size "$replica_size"
  fi

  # 启用rados应用 (--yes-i-really-mean-it 跳过已启用时的确认)
  ceph osd pool application enable "$pool_name" rados --yes-i-really-mean-it 2>/dev/null || true
}

echo "[1/6] 创建存储池..."

# PG数量设为32，适合3个OSD的小集群，避免超出 mon_max_pg_per_osd 限制
create_pool_if_not_exists sync_pool 32 2
create_pool_if_not_exists perf_pool 32 2
create_pool_if_not_exists warm_pool 32 2
create_pool_if_not_exists cold_pool 32 2

echo ""
echo "[2/6] 配置CRUSH规则 (如果有SSD/HDD OSD class)..."
# 如果集群有设置device class, 可以用以下命令:
# ceph osd crush rule create-replicated warm_rule default host ssd
# ceph osd crush rule create-replicated cold_rule default host hdd
# ceph osd pool set warm_pool crush_rule warm_rule
# ceph osd pool set cold_pool crush_rule cold_rule
echo "  (跳过 - 请根据实际集群配置手动设置CRUSH规则)"

echo ""
echo "[3/6] 创建热层ramfs..."
sudo mkdir -p /mnt/hot
if mountpoint -q /mnt/hot 2>/dev/null; then
    echo "  ✓ /mnt/hot 已挂载"
else
    sudo mount -t ramfs ramfs /mnt/hot
    sudo chmod 777 /mnt/hot
    echo "  ✓ ramfs已挂载到 /mnt/hot"
fi

echo ""
echo "[4/6] 验证Ceph连接..."
ceph -s
echo ""
rados lspools

echo ""
echo "[5/6] 检查Pool状态..."
for pool in sync_pool perf_pool warm_pool cold_pool; do
    obj_count=$(rados -p "$pool" ls 2>/dev/null | wc -l || echo "0")
    echo "  $pool: ${obj_count}个对象"
done

echo ""
echo "[6/6] 安装Python依赖..."
pip3 install flask flask-cors --break-system-packages 2>/dev/null \
  || pip3 install flask flask-cors 2>/dev/null \
  || echo "  ⚠ pip安装失败，请手动执行: pip3 install flask flask-cors"

echo ""
echo "=========================================="
echo "  初始化完成！"
echo "  启动后端: python3 app.py"
echo "  节点A: CURRENT_NODE=A python3 app.py"
echo "  节点B: CURRENT_NODE=B PORT=5001 python3 app.py"
echo "=========================================="