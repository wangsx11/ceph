# PF-3 Summary

- Metric: RDMA 网络环境下 QoS 事件优先级传输能力
- Source: `docs/性能要求.md` 第 3 条
- Generated At: 2026-05-27T19:49:28+0800
- Key Result: hi=142398.0 ops/s, lo=82222.0 ops/s, gain=73.19%
- Threshold: 高优先级相对低优先级处理效率提升 >= 22.0%
- Result: PASS
- Result Dir: /home/wangshouxin/native-rdma-web/performances/PF-3/history/web_20260527_194848_pf_PF3_20260527_194848_bcb25c1a
- Raw JSON: /home/wangshouxin/native-rdma-web/performances/PF-3/history/web_20260527_194848_pf_PF3_20260527_194848_bcb25c1a/raw.json
- Run Log: /home/wangshouxin/native-rdma-web/performances/PF-3/history/web_20260527_194848_pf_PF3_20260527_194848_bcb25c1a/logs/run.log

## 测试结论

- 高优先级吞吐：142398.0 ops/s。
- 低优先级吞吐：82222.0 ops/s。
- 高优先级吞吐是低优先级的 1.73x，相对低优先级提升 73.19%。
- 验收要求：提升比例 >= 22.0%；本次超过阈值 51.19 个百分点。
- 判定：PASS。

## 关键统计值

| Key | Value |
|---|---:|
| `hi_ops` | 142398.0 |
| `lo_ops` | 82222.0 |
| `gain_pct` | 73.19 |
| `threshold_gain_pct` | 22.0 |
| `hi_fail` | 0 |
| `lo_fail` | 0 |
| `hi_degraded` | 0 |
| `lo_degraded` | 0 |
| `hi_p99_us` | 51.16 |
| `lo_p99_us` | 200.72 |
| `qos_mode` | adaptive_data_plane |
| `configured_lo_rate_limit_kops` | 100 |
| `configured_hi_window_us` | data-plane-default |
| `configured_lo_burst_ms` | data-plane-default |

## 统计口径

- `gain_pct = (hi_ops - lo_ops) / lo_ops * 100%`。
- 高、低优先级并发压测，分别统计 measured 窗口内完成效率。
- QoS 由数据面自适应触发：检测到高优先级压力时，低优先级进入 token-bucket 保护；没有高优先级压力时，低优先级不被额外限速。
- 不统计构建、脚本启动、环境启动和 warmup 时间。
