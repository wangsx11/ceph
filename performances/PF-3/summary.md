# PF-3 Summary

- Metric: RDMA 网络环境下 QoS 事件优先级传输能力
- Source: `docs/性能要求.md` 第 3 条
- Generated At: 2026-05-04T00:20:51+0800
- Key Result: hi=300803.0 ops/s, lo=197340.0 ops/s, gain=52.43%
- Threshold: 高优先级相对低优先级处理效率提升 >= 22%
- Result: PASS
- Result Dir: /home/wangshouxin/native-rdma-web/performances/PF-3
- Raw JSON: /home/wangshouxin/native-rdma-web/performances/PF-3/raw.json
- Run Log: /home/wangshouxin/native-rdma-web/performances/PF-3/logs/run.log

## 关键统计值

| Key | Value |
|---|---:|
| `hi_ops` | 300803.0 |
| `lo_ops` | 197340.0 |
| `gain_pct` | 52.43 |
| `threshold_gain_pct` | 22.0 |
| `hi_fail` | 0 |
| `lo_fail` | 692 |
| `hi_degraded` | 0 |
| `lo_degraded` | 0 |
| `hi_p99_us` | 44.95 |
| `lo_p99_us` | 193.06 |
| `lo_rate_limit_kops` | 200 |

## 统计口径

- `gain_pct = (hi_ops - lo_ops) / lo_ops * 100%`。
- 高、低优先级并发压测，分别统计 measured 窗口内完成效率。
- QoS 通过 token-bucket 限速器约束低优先级吞吐，高优先级不限速。
- 不统计构建、脚本启动、环境启动和 warmup 时间。
