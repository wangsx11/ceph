# PF-8 Summary

- Metric: RDMA 网络环境下仿真引擎运行能力
- Source: `docs/性能要求.md` 第 8 条
- Generated At: 2026-05-04T00:23:32+0800
- Key Result: speedup=1.4299x, events/s=142993.0
- Threshold: speedup >= 1.0
- Result: PASS
- Result Dir: /home/wangshouxin/native-rdma-web/performances/PF-8
- Raw JSON: /home/wangshouxin/native-rdma-web/performances/PF-8/raw.json
- Raw CSV: 未生成
- Run Log: /home/wangshouxin/native-rdma-web/performances/PF-8/logs/run.log

## 关键统计值

| Key | Value |
|---|---:|
| `sim_nodes` | 4 |
| `entities` | 100000 |
| `events` | 1000000 |
| `threads` | 4 |
| `step_us` | 10 |
| `stress` | 20000 |
| `wall_s` | 6.993339 |
| `sim_s` | 10.0 |
| `speedup` | 1.4299 |
| `events_per_sec` | 142993.0 |

## 统计口径

- 测试逻辑由 `native_rdma/tests/performance/perf_08_simulation.sh` 迁移到本 `run.py`。
- 通过数据面 UDS 发送 `RPC_SIM_RUN`，统计仿真运行窗口。
- `speedup = simulated_seconds / wall_seconds`。
