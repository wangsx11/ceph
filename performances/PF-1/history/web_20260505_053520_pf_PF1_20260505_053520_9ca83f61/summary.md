# PF-1 Summary

- Metric: RDMA 网络环境分布式通讯能力
- Source: `docs/性能要求.md` 第 1 条
- Generated At: 2026-05-05T05:37:14+0800
- Threshold (A): 1KB 对象吞吐量 >= 1,000,000 ops/s
- Threshold (B): 大对象带宽利用率 >= 50%（按 RDMA 网络发送带宽计算）
- Result: FAIL
- Result Dir: /home/wangshouxin/native-rdma-web/performances/PF-1/history/web_20260505_053520_pf_PF1_20260505_053520_9ca83f61
- Raw JSON: /home/wangshouxin/native-rdma-web/performances/PF-1/history/web_20260505_053520_pf_PF1_20260505_053520_9ca83f61/raw.json
- Run Log: /home/wangshouxin/native-rdma-web/performances/PF-1/history/web_20260505_053520_pf_PF1_20260505_053520_9ca83f61/logs/run.log

## Sub-test A: 1KB 小对象吞吐

| Key | Value |
|---|---:|
| `ops_threads` | 4 |
| `ops_val_size` | 1024 |
| `ops_per_sec` | 331780.0 |
| `ops_fail` | 0 |
| `ops_degraded` | 0 |
| `passed_ops` | False |
| `ops_success_rate_pct` | 100.0% |
| `ops_fail_pct` | 0.0% |

## Sub-test B: 大对象带宽利用率

- Network Bandwidth Utilization: 44.71% / threshold 50.0%
- Network TX Bandwidth: avg=44.707 Gbps, peak=47.899 Gbps
- Success Rate: 100.0%

| Key | Value |
|---|---:|
| `bw_threads` | 4 |
| `bw_val_size` | 1048576 |
| `bw_network_tx_gbps_avg` | 44.707 |
| `bw_network_tx_gbps_peak` | 47.899 |
| `bw_link_gbps` | 100.0 |
| `bw_util_pct` | 44.71 |
| `bw_fail` | 0 |
| `bw_degraded` | 0 |
| `passed_util` | False |
| `bw_success_rate_pct` | 100.0% |
| `bw_fail_pct` | 0.0% |

### 大对象线程扫描

| Threads | Network Utilization | Network TX Avg Gbps | Network TX Peak Gbps | Client Req Gbps | Success Rate | Fail Count | Fail Rate | Result |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 2 | 27.44% | 27.44 | 44.292 | 27.126 | 100.000% | 0 | 0.0% | FAIL |
| 3 | 37.28% | 37.279 | 39.259 | 37.532 | 100.000% | 0 | 0.0% | FAIL |
| 4 | 44.71% | 44.707 | 47.899 | 44.836 | 100.000% | 0 | 0.0% | FAIL |

## 统计口径

- 1KB 小对象吞吐和大对象带宽利用率分项验收，两项均通过则 PASS。
- 两个子项都要求失败数为 0；任何 `ops_fail` 都不计入通过结果。
- 小对象测试使用 batch PUT 模式，计算 ops_per_sec。
- 大对象测试使用 1MB 对象，带宽利用率基于数据面 shared-memory metrics 的 `bw_tx_gbps` 计算，即 RDMA 网络发送带宽。
- `req_bytes` 只作为客户端请求字节辅助数据，不用于网络带宽利用率判定。
- 不统计构建、脚本启动、环境启动和 warmup 时间。
