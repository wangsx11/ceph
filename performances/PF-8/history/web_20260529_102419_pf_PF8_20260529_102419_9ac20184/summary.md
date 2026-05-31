# PF-8 Summary

- Metric: RDMA 网络环境下仿真引擎运行能力
- Source: `docs/性能要求.md` 第 8 条
- Generated At: 2026-05-29T10:24:22+0800
- Key Result: speedup=6.2476x, events/s=624760.0
- Threshold: 100000 entities, entity_size=1024B, 1000000 events, speedup >= 1.0
- Result: PASS
- Result Dir: /home/wangshouxin/native-rdma-web/performances/PF-8/history/web_20260529_102419_pf_PF8_20260529_102419_9ac20184
- Raw JSON: /home/wangshouxin/native-rdma-web/performances/PF-8/history/web_20260529_102419_pf_PF8_20260529_102419_9ac20184/raw.json
- Raw CSV: 未生成
- Run Log: /home/wangshouxin/native-rdma-web/performances/PF-8/history/web_20260529_102419_pf_PF8_20260529_102419_9ac20184/logs/run.log

## 关键统计值

| Key | Value |
|---|---:|
| `sim_nodes` | 4 |
| `entities` | 100000 |
| `entity_size` | 1024 |
| `entity_bytes` | 102400000 |
| `events` | 1000000 |
| `threads` | 4 |
| `step_us` | 10 |
| `stress` | 4000 |
| `wall_s` | 1.600616 |
| `sim_s` | 10.0 |
| `speedup` | 6.2476 |
| `events_per_sec` | 624760.0 |
| `captured_events` | 3908 |
| `captured_dropped` | 0 |

## 统计口径

- 测试逻辑由 `native_rdma/tests/performance/perf_08_simulation.sh` 迁移到本 `run.py`。
- 通过数据面 UDS 发送 `RPC_SIM_RUN`，统计仿真运行窗口。
- 数据面按 `entity_size` 为每个仿真实体分配 payload；默认实体大小为 1024B。
- `speedup = simulated_seconds / wall_seconds`。
