# CEPH + RDMA 集群测试与优化项目

基于 RDMA 底层在三节点集群上部署 CEPH 后，本仓库提供：

1. **完整功能测试脚本**（`tests/functional/`）——对照《功能要求.md》三大模块。
2. **完整性能测试方案**（`tests/performance/`）——对照《性能要求.md》9 项指标。
3. **高性能后端重写**（`backend_v2/`）——针对演示场景 3/5/6 最大化激发
   CEPH + RDMA 潜力，保留原有 API 兼容性。

## 目录总览

```
ceph/
├── docs/                        # 原始需求（只读）
│   ├── 功能要求.md
│   ├── 性能要求.md
│   ├── 演示要求.md
│   └── 部署指南.md
├── backend/                     # 旧版后端（保留）
├── backend_v2/                  # ★ 高性能重写后端
│   ├── app.py                   # Flask 入口
│   ├── ceph_manager.py          # 连接 + IOContext 缓存
│   ├── rdma_counters.py         # 读 /sys IB 计数器
│   ├── rdma_mempool.py          # 分布式内存池
│   ├── metrics.py               # 无锁计数 & 延迟直方图
│   ├── simulation_engine.py     # 仿真引擎
│   ├── m3_sync.py / m5_perf.py / m6_tiering.py
│   ├── setup_pools.sh
│   ├── requirements.txt
│   ├── PERFORMANCE_NOTES.md     # ★ 性能优化说明
│   └── README.md
├── tests/                       # ★ 测试套件
│   ├── common/ceph_helper.py
│   ├── functional/
│   │   ├── storage_heterogeneous/   # 模块一 6 项
│   │   ├── rdma_distributed/        # 模块二 5 项
│   │   └── memory_pool/             # 模块三 6 项
│   ├── performance/
│   │   ├── baseline/                # 时延 / 带宽基准
│   │   ├── stress/                  # 压力 & QoS
│   │   └── rdma_network/            # RDMA 诊断
│   ├── run_all_functional.sh
│   └── run_all_performance.sh
└── dashboard/                   # 前端（兼容旧版）
```

## 快速开始

```bash
# 1. 初始化 pool 与 ramfs（首次运行）
bash backend_v2/setup_pools.sh

# 2. 启动高性能后端
cd backend_v2
python3 app.py                               # 节点 A, 默认 0.0.0.0:5000
CURRENT_NODE=B PORT=5000 python3 app.py      # 节点 B

# 3. 运行功能测试
bash tests/run_all_functional.sh

# 4. 运行性能测试（会写报告到 tests/reports/*.json）
bash tests/run_all_performance.sh
python3 tests/performance/summary.py
```

## 对照要求的交付映射

| 要求 | 位置 |
|------|------|
| 功能要求 § 多级异构存储 | `tests/functional/storage_heterogeneous/` |
| 功能要求 § RDMA 分布式 | `tests/functional/rdma_distributed/` |
| 功能要求 § 内存池化 | `tests/functional/memory_pool/` + `backend_v2/rdma_mempool.py` |
| 性能要求 9 项指标 | `tests/performance/**` |
| 演示要求 场景 3 跨节点同步 | `backend_v2/m3_sync.py` |
| 演示要求 场景 5 吞吐-规模影响 | `backend_v2/m5_perf.py` |
| 演示要求 场景 6 分级存储 | `backend_v2/m6_tiering.py` |
| 性能优化说明 | `backend_v2/PERFORMANCE_NOTES.md` |

## 设计要点

- **IOContext 复用**：基于 `ms_type=async+rdma`，同 pool 内所有请求共享
  一条 RDMA QP，极大降低 connect / handshake 次数。
- **Async Batch 流水线**：热路径使用 `aio_*` + inflight window = 32，让
  librados 的 RDMA send ring 保持满载。
- **mmap 热层**：`/mnt/hot` ramfs + `MAP_POPULATE` 读取，避免 page fault。
- **COW 快照**：冷层备份用 `ioctx.create_snap`，O(1) metadata 操作。
- **直读 IB 计数器**：实时吞吐/利用率来自 `/sys/class/infiniband/*/counters/`，
  零侵入采样。

更多调优细节见 `backend_v2/PERFORMANCE_NOTES.md`。
