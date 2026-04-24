# RDMA 分布式仿真计算模块 — 功能测试

对照《功能要求.md》该模块 5 项子功能，每项独立测试脚本。

## 子功能覆盖矩阵

| 编号 | 功能点 | 测试脚本 | 核心断言 |
|------|--------|----------|----------|
| 1 | RDMA + TCP/IP 统一通信层 | `test_01_protocol_switch.py` | 同一 API 在 `ms_type=async+rdma` 和 `async+posix` 下均可工作 |
| 2 | 聚合数据传输 | `test_02_batch_aggregation.py` | 单批 1000 × 1KB 对象耗时 ≤ 200ms |
| 3 | 流量优先级 QoS | `test_03_qos_priority.py` | 高优先级吞吐比低优先级提升 ≥ 22% |
| 4 | CPU/GPU 直通访问 (GPUDirect) | `test_04_gpu_direct.py` | 存在 `nvidia-peermem` 时跳过拷贝；不存在则以 pageable/pinned 内存对照 |
| 5 | 路由转发与负载均衡 | `test_05_routing_lb.py` | 多 QP 并发下，流量在 ≥ 2 个 OSD host 间均衡 |

## 运行

```bash
python3 tests/functional/rdma_distributed/test_02_batch_aggregation.py
bash   tests/functional/rdma_distributed/run.sh
```

## 前置条件

- `ibstat` 至少一个端口 `State: Active`
- `ceph config get global ms_type` 含 `rdma` 字样
- `ib_send_bw`、`ib_write_bw`、`ib_read_lat` 在 PATH 中
