# -*- coding: utf-8 -*-
"""Mock 全局配置 — 基线值与波动范围"""

# M3 基线
M3_SYNC_LATENCY_US_MEAN = 35.0       # 平均同步延迟 (μs)
M3_SYNC_LATENCY_US_STD = 5.0         # 标准差
M3_SYNC_LATENCY_P99_MEAN = 85.0      # P99 延迟 (μs)
M3_CROSS_NODE_LATENCY_MIN = 30.0     # 跨节点延迟下限 (μs)
M3_CROSS_NODE_LATENCY_MAX = 50.0     # 跨节点延迟上限 (μs)
M3_WRITE_LATENCY_MS_MEAN = 0.035     # 写操作延迟 (ms), 即 ~35μs
M3_WRITE_LATENCY_MS_STD = 0.005

# M5 三轮基线
M5_ROUNDS = {
    1: {
        "count": 10000,
        "iops": 1050000, "iops_std": 31500,       # ±3%
        "tp": 1025.0, "tp_std": 30.75,
        "avg_lat": 42.0, "avg_lat_std": 1.26,
        "p50": 38.0, "p50_std": 1.14,
        "p99": 88.0, "p99_std": 2.64,
        "rdma": 980.0, "rdma_std": 29.4,
        "net_util": 57.0, "net_util_std": 1.5,    # 网络使用率 ~57%
    },
    2: {
        "count": 50000,
        "iops": 980000, "iops_std": 29400,
        "tp": 957.0, "tp_std": 28.71,
        "avg_lat": 45.0, "avg_lat_std": 1.35,
        "p50": 41.0, "p50_std": 1.23,
        "p99": 92.0, "p99_std": 2.76,
        "rdma": 920.0, "rdma_std": 27.6,
        "net_util": 55.0, "net_util_std": 1.5,    # 网络使用率 ~55%
    },
    3: {
        "count": 100000,
        "iops": 920000, "iops_std": 27600,
        "tp": 898.0, "tp_std": 26.94,
        "avg_lat": 48.0, "avg_lat_std": 1.44,
        "p50": 44.0, "p50_std": 1.32,
        "p99": 96.0, "p99_std": 2.88,
        "rdma": 870.0, "rdma_std": 26.1,
        "net_util": 53.0, "net_util_std": 1.5,    # 网络使用率 ~53%
    },
}

# M5 测试持续时间（秒）和预填充时间模拟
M5_PREPARE_SECONDS = 3
M5_TEST_DURATION = 12

# M6 基线
M6_HOT_READ_GBS = 20.0          # 热层读速率 GB/s
M6_HOT_READ_STD = 1.0
M6_WARM_WRITE_GBS = 10.0        # 温层写速率 GB/s
M6_WARM_WRITE_STD = 0.5
M6_COLD_READ_MBS = 250.0        # 冷层读速率 MB/s
M6_COLD_READ_STD = 25.0
M6_P999_WRITE_LATENCY_MS = 0.8  # P999 写入延迟 (ms)
M6_P999_WRITE_STD = 0.05
M6_MIGRATION_COOLDOWN = 120
