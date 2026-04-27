# -*- coding: utf-8 -*-
"""全局配置"""
import os

CEPH_CONF = os.environ.get("CEPH_CONF", "/etc/ceph/ceph.conf")

# 各模块使用的 Pool 名称
SYNC_POOL = os.environ.get("SYNC_POOL", "sync_pool")       # M3: 跨节点同步
PERF_POOL = os.environ.get("PERF_POOL", "perf_pool")       # M5: 性能测试
WARM_POOL   = os.environ.get("WARM_POOL",   "warm_pool")   # M6: 温层(SSD)
COLD_POOL   = os.environ.get("COLD_POOL",   "cold_pool")   # M6: 冷层(HDD)
BACKUP_POOL = os.environ.get("BACKUP_POOL", "backup_pool") # M6: 备份池(独立于冷层)
HOT_PATH    = os.environ.get("HOT_PATH",    "/mnt/hot")    # M6: 热层(DRAM/ramfs)

# 节点信息
NODE_A = {"name": "xfusion3", "role": "前线指挥所", "ip": "192.168.0.3"}
NODE_B = {"name": "xfusion4", "role": "后方指挥中心", "ip": "192.168.0.4"}
CURRENT_NODE = os.environ.get("CURRENT_NODE", "A")

# M6 分级存储参数
THRESHOLD_HOT    = 3.0
THRESHOLD_WARM   = 1.0
DEMOTE_HOT       = 2.0
DEMOTE_WARM      = 0.5
TIME_DECAY_ALPHA = 0.3
TIME_WINDOW      = 7200
MIGRATION_COOLDOWN = 120

# 使用用户目录存储临时文件，避免权限问题
TIERING_DATA_DIR = os.path.expanduser("~/ceph-web/data")
os.makedirs(TIERING_DATA_DIR, exist_ok=True)
STATS_FILE       = os.path.join(TIERING_DATA_DIR, "access_stats.json")
MIGRATION_FILE   = os.path.join(TIERING_DATA_DIR, "migration_history.json")
TIERING_LOG_FILE = os.path.join(TIERING_DATA_DIR, "tiering.log")

# RDMA 链路带宽（Gbps），用于网络使用率换算；通过环境变量按实际网卡型号调整
RDMA_LINK_BANDWIDTH_GBPS = float(os.environ.get("RDMA_LINK_BANDWIDTH_GBPS", "100"))
