# backend_v2 — High-performance Ceph + RDMA backend

演示场景（对照 docs/演示要求.md）：

- **场景 3**：跨节点对象读写与数据同步
- **场景 5**：系统吞吐量与实体数量对性能的影响
- **场景 6**：分级存储（DRAM / SSD / HDD）

本模块是对 `backend/` 的完整重写，目标是 **最大化压榨 CEPH + RDMA 的硬件
潜力**。设计原则：

1. **零额外拷贝**：所有热路径使用 `librados` 的 `aio_*` + `bytes`/`memoryview`，
   绕开 Python 层字符串拷贝；对象体积 >= 64KB 时使用 `writesame`/`append`
   而非 `write_full`。
2. **持久化 IOContext**：每 pool 一个进程常驻 IOContext，避免每次请求重建，
   librados 内部复用 OSD session（基于 RDMA QP）。
3. **批量聚合提交**：同 PG 的对象合并提交、以 `Completion` 列表一次性
   `wait_for_complete`，让 OSD 端享受 RDMA `post_send` 批量调度。
4. **线程池 + 无锁计数**：指标采集使用原子整型 + 无锁环缓冲，避免 Python
   GIL 瓶颈。
5. **RDMA counters 直读**：通过 `/sys/class/infiniband/*/ports/*/counters/`
   每秒采样 `port_rcv_data` / `port_xmit_data`，折算实时带宽和利用率。
6. **缓存 + 直写 Tiering**：热层 ramfs 采用 mmap + `MAP_POPULATE`，温/冷
   层使用 `ioctx.aio_write_full` + 并发批提交。

## 文件布局

| 文件 | 作用 |
|------|------|
| `app.py` | Flask 入口，注册三个 Blueprint |
| `config.py` | 配置集中点（环境变量驱动） |
| `ceph_manager.py` | 单例 + 每 pool 懒加载 IOContext 缓存 |
| `rdma_counters.py` | 读取 /sys IB counters，计算实时 BW 与利用率 |
| `rdma_mempool.py` | 分布式内存池 API（本地 DRAM + 远端 RADOS） |
| `metrics.py` | 无锁计数器、百分位环缓冲 |
| `simulation_engine.py` | 仿真引擎核心（batch aggregate + mempool） |
| `m3_sync.py` | 场景 3：跨节点同步（缓存元数据 + aio） |
| `m5_perf.py` | 场景 5：压测引擎（进程内多线程 batch） |
| `m6_tiering.py` | 场景 6：三层分级（ramfs mmap + aio batch） |

## 启动

```bash
cd backend_v2
python3 app.py                               # 节点 A
CURRENT_NODE=B PORT=5001 python3 app.py      # 节点 B
```

API 完全兼容原 `backend/`：`/api/m3/*`、`/api/m5/*`、`/api/m6/*`、`/api/health`。
