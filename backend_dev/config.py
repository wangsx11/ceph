# -*- coding: utf-8 -*-
"""backend_dev centralised config — env driven, single source of truth."""
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
SNAPSHOT_POOL = os.environ.get("SNAPSHOT_POOL", "snapshot_pool")
SNAPSHOT_RESTORE_POOL = os.environ.get("SNAPSHOT_RESTORE_POOL", "snapshot_restore_pool")

# === Tier paths ===
_default_hot_path = "/mnt/hot" if os.path.isdir("/mnt/hot") and os.access("/mnt/hot", os.W_OK) else "/dev/shm/ceph_web_hot"
HOT_PATH = os.environ.get("HOT_PATH", _default_hot_path)

# === Node identity ===
NODE_A = {
    "name": "xfusion3",
    "role": "前线指挥所",
    "ip": os.environ.get("NODE_A_IP", "192.168.0.218"),
    "mgmt_ip": os.environ.get("NODE_A_MGMT_IP", "10.26.42.224"),
}
NODE_B = {
    "name": "xfusion4",
    "role": "后方指挥中心",
    "ip": os.environ.get("NODE_B_IP", "192.168.0.214"),
    "mgmt_ip": os.environ.get("NODE_B_MGMT_IP", "10.26.42.225"),
}
CURRENT_NODE = os.environ.get("CURRENT_NODE", "A")
NODE_A_API = os.environ.get("NODE_A_API", f"http://{NODE_A['mgmt_ip']}:5000")
NODE_B_API = os.environ.get("NODE_B_API", f"http://{NODE_B['mgmt_ip']}:5000")

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
PERF_REMOTE_TRIGGER = os.environ.get("PERF_REMOTE_TRIGGER", "1") == "1"
PERF_MODE = os.environ.get("PERF_MODE", "ceph_aggregate")
PERF_AGG_SEGMENT_RECORDS = int(os.environ.get("PERF_AGG_SEGMENT_RECORDS", "1024"))
RDMA_PERF_DEVICE = os.environ.get("RDMA_PERF_DEVICE", "mlx5_0")
RDMA_PERF_PORT = os.environ.get("RDMA_PERF_PORT", "1")
RDMA_PERF_GID_INDEX = os.environ.get("RDMA_PERF_GID_INDEX", "3")
RDMA_PERF_PEER_HOST = os.environ.get("RDMA_PERF_PEER_HOST", "xfusion5")
RDMA_PERF_PEER_IP = os.environ.get("RDMA_PERF_PEER_IP", "192.168.0.215")
RDMA_PERF_PEER_GID_INDEX = os.environ.get("RDMA_PERF_PEER_GID_INDEX", "5")
RDMA_PERF_SIZE = int(os.environ.get("RDMA_PERF_SIZE", str(1024 * 1024)))
RDMA_PERF_ITERS = int(os.environ.get("RDMA_PERF_ITERS", "5000"))
_obj_counts_env = os.environ.get("PERF_OBJ_COUNTS", "")
if _obj_counts_env:
    OBJ_COUNTS = {}
    for item in _obj_counts_env.split(","):
        key, value = item.split(":", 1)
        OBJ_COUNTS[int(key)] = int(value)
else:
    OBJ_COUNTS = {1: 10_000, 2: 50_000, 3: 100_000}

# === Snapshot defaults ===
SNAPSHOT_DEFAULT_COUNT = int(os.environ.get("SNAPSHOT_DEFAULT_COUNT", "10000"))
SNAPSHOT_OBJECT_SIZE = int(os.environ.get("SNAPSHOT_OBJECT_SIZE", "1024"))
SNAPSHOT_BATCH = int(os.environ.get("SNAPSHOT_BATCH", "512"))

# === Data dir ===
DATA_DIR = os.environ.get("BACKEND_DEV_DATA", os.path.expanduser("~/ceph-web/data"))
SNAPSHOT_DIR = os.environ.get("SNAPSHOT_DIR", os.path.join(DATA_DIR, "snapshots"))
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(SNAPSHOT_DIR, exist_ok=True)
