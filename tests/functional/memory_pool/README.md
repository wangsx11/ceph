# 一致性总线内存池化仿真计算模块 — 功能测试

对照《功能要求.md》第三模块的 6 项子功能。

## 子功能覆盖矩阵

| 编号 | 功能点 | 测试脚本 | 核心断言 |
|------|--------|----------|----------|
| 1 | RDMA 零拷贝远程访问 | `test_01_zero_copy_rdma.py` | `ib_read_lat` 平均延迟 ≤ 5μs |
| 2 | 分布式内存池 API | `test_02_mempool_api.py` | alloc/free/read/write 四段 API 往返一致 |
| 3 | 统一命名机制 | `test_03_namespace.py` | 不同节点通过 `pool.region` 访问同一块共享内存 |
| 4 | 本地/远端自适应分配 | `test_04_adaptive_alloc.py` | 热对象本地分配，冷对象远端分配，切换触发 |
| 5 | 任务/用户级隔离 | `test_05_isolation.py` | 不同 namespace 相互不可见，鉴权失败即拒绝 |
| 6 | 故障高可用 | `test_06_ha_failover.py` | 关闭一个 OSD 后仍可读写；恢复后数据一致 |

内存池 API 通过 `backend_v2/rdma_mempool.py` 提供（见项目高性能后端）。

## 运行

```bash
python3 tests/functional/memory_pool/test_01_zero_copy_rdma.py
bash tests/functional/memory_pool/run.sh
```
