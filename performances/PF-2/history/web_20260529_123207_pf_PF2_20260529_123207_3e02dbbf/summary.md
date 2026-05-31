# PF-2 Summary

- Metric: RDMA 网络环境下对象传输能力
- Source: `docs/性能要求.md` 第 2 条
- Generated At: 2026-05-29T12:32:09+0800
- Samples: 31332/100000
- Key Result: avg=31.48us, p99=50.73us
- Threshold: 平均时延 <= 50us；P99 <= 100us；样本数 >= 100,000
- Result: FAIL
- Result Dir: /home/wangshouxin/native-rdma-web/performances/PF-2/history/web_20260529_123207_pf_PF2_20260529_123207_3e02dbbf
- Raw JSON: /home/wangshouxin/native-rdma-web/performances/PF-2/history/web_20260529_123207_pf_PF2_20260529_123207_3e02dbbf/raw.json
- Run Log: /home/wangshouxin/native-rdma-web/performances/PF-2/history/web_20260529_123207_pf_PF2_20260529_123207_3e02dbbf/logs/run.log

## 关键统计值

| Key | Value |
|---|---:|
| `samples` | 31332 |
| `lat_avg_us` | 31.48 |
| `lat_p50_us` | 28.03 |
| `lat_p99_us` | 50.73 |
| `lat_p99_9_us` | 116.88 |
| `lat_max_us` | 30510.83 |
| `ops_fail` | 0 |
| `ops_degraded` | 0 |
| `max_iops` | 105000 |

## 统计口径

- 统计 measured 窗口内成功 1KB 对象的数据面端到端传输时延。
- 使用 PUT 操作衡量对象传输能力（写入本地 slab + 同步等待 RDMA WRITE 完成）。
- 失败样本单独计数，不混入成功样本分位数。
- 不统计构建、脚本启动、环境启动和 warmup 时间。
