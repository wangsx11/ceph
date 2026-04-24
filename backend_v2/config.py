# -*- coding: utf-8 -*-
"""backend_v2 centralised config — env driven, single source of truth."""
import os

CEPH_CONF = os.environ.get("CEPH_CONF", "/etc/ceph/ceph.conf")
CEPH_USER = os.environ.get("CEPH_USER", "client.admin")

# === Pools ===
SYNC_POOL   = os.environ.get("SYNC_POOL",   "sync_pool")
PERF_POOL   = os.environ.get("PERF_POOL",   "perf_pool")
WARM_POOL   = os.environ.get("WARM_POOL",   "warm_pool")
COLD_POOL   = os.environ.get("COLD_POOL",   "cold_pool")
BACKUP_POOL = os.environ.get("BACKUP_POOL", "backup_pool")
MEMPOOL_POOL = os.environ.get("MEMPOOL_POOL", "mempool_pool")

# === Tier paths ===
HOT_PATH = os.environ.get("HOT_PATH", "/mnt/hot")

# === Node identity ===
NODE_A = {"name": "nodeA", "role": "前线指挥所", "ip": os.environ.get("NODE_A_IP", "192.168.0.3")}
NODE_B = {"name": "nodeB", "role": "后方指挥中心", "ip": os.environ.get("NODE_B_IP", "192.168.0.4")}
CURRENT_NODE = os.environ.get("CURRENT_NODE", "A")

# === Tiering heuristics ===
THRESHOLD_HOT  = float(os.environ.get("THRESHOLD_HOT",  "3.0"))
THRESHOLD_WARM = float(os.environ.get("THRESHOLD_WARM", "1.0"))
DEMOTE_HOT     = float(os.environ.get("DEMOTE_HOT",     "2.0"))
DEMOTE_WARM    = float(os.environ.get("DEMOTE_WARM",    "0.5"))
TIME_DECAY     = float(os.environ.get("TIME_DECAY",     "0.3"))
TIME_WINDOW    = int(os.environ.get("TIME_WINDOW",      "7200"))
MIGRATION_COOLDOWN = int(os.environ.get("MIGRATION_COOLDOWN", "120"))

# === RDMA link params (used only for utilisation calculations) ===
RDMA_LINK_GBPS = float(os.environ.get("RDMA_LINK_BANDWIDTH_GBPS", "100"))
LINK_BW_MBPS = RDMA_LINK_GBPS * 1024.0 / 8.0

# === Perf defaults ===
PERF_OBJ_SIZE   = int(os.environ.get("PERF_OBJ_SIZE",   str(1024)))
PERF_CONCURRENCY = int(os.environ.get("PERF_CONCURRENCY", "64"))
PERF_DURATION   = int(os.environ.get("PERF_DURATION",   "12"))
PERF_READ_RATIO = float(os.environ.get("PERF_READ_RATIO", "0.7"))
OBJ_COUNTS = {1: 10_000, 2: 50_000, 3: 100_000}

# === Data dir ===
DATA_DIR = os.environ.get("BACKEND_V2_DATA", os.path.expanduser("~/ceph-web/data_v2"))
os.makedirs(DATA_DIR, exist_ok=True)
