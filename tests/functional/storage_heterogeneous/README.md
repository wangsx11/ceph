# 多级异构高效能存储模块 — 功能测试

对照《功能要求.md》中该模块的 6 项子功能，每项独立测试脚本。

## 子功能覆盖矩阵

| 编号 | 功能点 | 测试脚本 | 核心断言 |
|------|--------|----------|----------|
| 1 | 异构设备统一访问 | `test_01_heterogeneous_access.py` | NVMe / SATA-SSD / ZNS-SSD 三类 device class 均可通过统一 RADOS 接口读写 |
| 2 | 多层感知 + 冷热分离 | `test_02_tier_hotcold.py` | 高频访问对象落入 warm_pool，低频下沉到 cold_pool |
| 3 | 多策略预取 | `test_03_prefetch.py` | 顺序/随机/回放三种访问模式下，预取命中率 ≥ 70% |
| 4 | 压缩与去重 | `test_04_compression_dedup.py` | 开启 `compression_algorithm=zstd` 后，压缩比 ≥ 1.5×；相同数据仅存一份 |
| 5 | IO 优先级调度 | `test_05_io_priority.py` | 高优先级前台 IO 的 P99 延迟不受后台压缩/GC 影响（<+10%） |
| 6 | 运行中数据采集 | `test_06_live_capture.py` | 写入过程中可并发读取对象最新状态，无锁阻塞 |

## 运行方式

```bash
# 单个
python3 tests/functional/storage_heterogeneous/test_02_tier_hotcold.py

# 全部
bash tests/functional/storage_heterogeneous/run.sh
```

## 前置条件

- 已创建 pools: `warm_pool`, `cold_pool`, `test_hetero_pool`
- Ceph 集群状态 HEALTH_OK
- 若无多 device class，脚本会自动 fallback 到单一 class 并打印 WARN
