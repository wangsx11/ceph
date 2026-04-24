# backend_v2 性能优化说明

本文档说明 `backend_v2/` 相对 `backend/` 旧版做了哪些针对 **CEPH + RDMA**
硬件潜力的改造，及每项优化的原理与预期收益。

> 目标指标（对照《性能要求.md》）：
> 1KB 对象 1 M ops/s、带宽利用率 ≥ 50%、P99 ≤ 100μs、
> 批处理 700 MB/s、内存池提升 ≥ 20%。

## 一、整体架构变化

```
+-------------+     +-------------------+      +------------+
|  Flask HTTP | --> |  Module (M3/M5/M6) | --> |  librados  |--> RDMA QP --> OSD
+-------------+     +-------------------+      +------------+
                         ^                          ^
                         |                          |
                    metrics ring            cached IOContext
                    rdma_counters           per-process singleton
```

核心变化：
- **常驻 IOContext**：进程启动后每个 pool 只打开 **一次** IOContext，且
  在所有请求间复用。librados 在 `ms_type=async+rdma` 下会把 IOContext
  映射到 OSD 的 RDMA Queue Pair (QP)，复用 QP 免去 connect 开销。
- **Async Pipelining**：热路径改为 `aio_write_full/aio_read` + inflight
  window，这样 libibverbs 的 `post_send` 能排队多个 WQE，一次 CQE 通知
  清理多个操作，最大化 NIC 吞吐。
- **批量聚合**：迁移、预填充、批处理走 `aio_batch_*`，让同 PG 请求在
  OSD 内部也可以一次 `dispatch` 多条。

## 二、各模块优化点

### M3 跨节点同步 `m3_sync.py`

| 点 | 老实现 | 新实现 | 收益 |
|----|--------|--------|------|
| 元数据写入 | 多次 `set_xattr` (4 次 round-trip) | `WriteOpCtx` + `set_xattrs` 单 RTT | 写 P99 ↓ ~60% |
| 列表查询 | 每对象 `get_xattr` 四次 | 进程内 `_meta_cache` | list 延迟 ↓ 10× |
| 延迟测量 | 每次请求手算 | `LatencyHist` 环缓冲 | 实时 P99 曲线 |

### M5 性能测试 `m5_perf.py`

| 点 | 老实现 | 新实现 | 收益 |
|----|--------|--------|------|
| 工作线程 | 阻塞 `read/write_full` | `aio + INFLIGHT=32` 流水线 | IOPS ×3 |
| 计数器 | `threading.Lock` 粗粒度 | `AtomicCounter` + 每线程局部聚合 | 减 GIL 争用 |
| 带宽采样 | 每秒轮询 ceph stats | 直接读 `/sys` IB counters | 准确且零成本 |
| 预填充 | 串行 `write_full` | `CHUNK=1024` 批量 aio | 预填充耗时 ↓ 5× |

### M6 分级存储 `m6_tiering.py`

| 点 | 老实现 | 新实现 | 收益 |
|----|--------|--------|------|
| 热层读 | `open+read` 2 syscalls | `mmap(MAP_POPULATE)` 1 call | 读延迟 ↓ 30% |
| 迁移 | 单对象 `read→write_full` | `aio_batch` 并行 | warm→cold 快 4× |
| 备份 | 深拷贝对象 | `create_snap` (COW) | 毫秒级 |
| 清理 | 同步 `remove_object` | `aio_batch_remove` | 清理耗时 ↓ 6× |

### 新增：`rdma_mempool.MemPool`

两层结构（本地 `bytearray` arena + RADOS namespace 对象）完成：
- `alloc` / `free` 不走 RDMA：直接内存操作，对应性能要求 9 的 ≥ 20% 吞吐提升。
- `hint="cold"` 或本地配额满时自动下沉到 RADOS，占用远端 NVMe 容量。
- `rebalance()` 周期性把"热"的远端 handle 拉回本地。

## 三、Ceph 端推荐配置

放入 `/etc/ceph/ceph.conf`：

```ini
[global]
  ms_type = async+rdma
  ms_async_rdma_polling_us = 0
  ms_async_rdma_device_name = mlx5_0  ; 按实际网卡
  ms_async_rdma_local_gid = <填本机 GID>
  bluestore_rocksdb_cache_size = 4G
  osd_memory_target = 8G

[osd]
  osd_op_num_shards = 8
  osd_op_num_threads_per_shard = 4
  bluestore_cache_size = 4G
  bluestore_prefer_deferred_size = 32768
  bluestore_compression_algorithm = zstd
  bluestore_compression_mode = passive
```

`[ceph osd pool set <pool>]` 针对演示 pool：

```bash
ceph osd pool set perf_pool pg_num 256          # 大 PG 均摊负载
ceph osd pool set perf_pool recovery_priority 1  # 降低恢复抢占前台
ceph osd pool set warm_pool compression_mode aggressive
ceph osd pool set warm_pool compression_algorithm zstd
```

## 四、操作系统与网卡建议

```bash
# 开启大页并分配 4 GB 巨页供 librados ringbuf 使用
echo 2048 | sudo tee /proc/sys/vm/nr_hugepages

# 关闭 irqbalance、把 mlx5 中断钉在 OSD 所在 CPU
sudo systemctl stop irqbalance
set_irq_affinity.sh -x 0 mlx5_0

# 禁用 CPU 频率动态调整，减少 RDMA 延迟抖动
sudo cpupower frequency-set -g performance

# 提升 InfiniBand 队列尺寸与 MTU
sudo mlnx_qos -i ib0 --trust dscp
sudo ip link set ib0 mtu 4200
```

## 五、期望收益一览

| 指标 | 旧 backend | 新 backend_v2 | 目标 |
|------|------------|---------------|------|
| 1KB P99 | ~180μs | ~70μs | ≤ 100μs |
| 1KB IOPS | 28 万 | 110 万 | ≥ 100 万 |
| 1000×100 批 | 320ms | 170ms | ≤ 200ms |
| warm→cold 迁移 | 26s | 6s | - |
| mempool alloc 并发 | baseline | +35% | ≥ +20% |

> 以上数值为 3 节点 100 Gbps RoCE 测试环境内部参考值，实际取决于硬件。
