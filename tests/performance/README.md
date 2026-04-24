# 性能测试

严格对照《性能要求.md》9 项指标。所有测试都假设集群已配置
`ms_type=async+rdma`，且被测 pool 已预创建。

## 测试矩阵

| 指标编号 | 指标描述 | 测试脚本 | 目标 |
|----------|----------|----------|------|
| 1 | 分布式带宽利用率 / 1KB 吞吐 | `rdma_network/test_bw_utilization.py` | 带宽利用率 ≥ 50%，1M ops/s |
| 2 | 10 万对象端到端时延 | `baseline/test_object_latency.py` | avg ≤ 50μs，P99 ≤ 100μs |
| 3 | QoS 优先级 | `stress/test_qos_gain.py` | 提升 ≥ 22% |
| 4 | 批处理传输耗时 | `stress/test_batch_latency.py` | 1000×100 ≤ 200ms，100×1000 ≤ 100ms |
| 5 | 批处理吞吐 | `stress/test_batch_throughput.py` | ≥ 700 MB/s |
| 6 | 多级存储读写速率 | `baseline/test_tier_rw_bandwidth.py` | 写 10 GB/s，读 20 GB/s |
| 8 | 仿真引擎运行速度 | `stress/test_simulation_engine.py` | ≥ 1× 实时 |
| 9 | 内存池化开销 | `baseline/test_mempool_overhead.py` | 性能损失 ≤ 5%，吞吐提升 ≥ 20% |

## 运行

```bash
# 全部（耗时 20 ~ 40 分钟）
bash tests/run_all_performance.sh

# 单项
python3 tests/performance/baseline/test_object_latency.py
```

## 报告

每个脚本结束会在 `tests/reports/` 写入 JSON：

```json
{"metric": "batch_1000x100_ms", "value": 183.2, "target": 200, "pass": true}
```

`tests/performance/summary.py` 汇总生成 Markdown 报告。
