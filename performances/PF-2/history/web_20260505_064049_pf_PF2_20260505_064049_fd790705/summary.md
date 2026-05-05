# PF-2 Summary

- Metric: RDMA 网络环境下对象传输能力
- Source: `docs/性能要求.md` 第 2 条
- Generated At: 2026-05-05T06:41:03+0800
- Samples: 2272705/100000
- Key Result: avg=34.68us, p99=48.26us
- Threshold: 平均时延 <= 50us；P99 <= 100us；样本数 >= 100,000
- Result: PASS
- Result Dir: /home/wangshouxin/native-rdma-web/performances/PF-2/history/web_20260505_064049_pf_PF2_20260505_064049_fd790705
- Raw JSON: /home/wangshouxin/native-rdma-web/performances/PF-2/history/web_20260505_064049_pf_PF2_20260505_064049_fd790705/raw.json
- Run Log: /home/wangshouxin/native-rdma-web/performances/PF-2/history/web_20260505_064049_pf_PF2_20260505_064049_fd790705/logs/run.log

## 关键统计值

| Key | Value |
|---|---:|
| `samples` | 2272705 |
| `lat_avg_us` | 34.68 |
| `lat_p50_us` | 31.41 |
| `lat_p99_us` | 48.26 |
| `lat_p99_9_us` | 72.39 |
| `lat_max_us` | 29382.29 |
| `ops_fail` | 0 |
| `ops_degraded` | 0 |

## 统计口径

- 统计 measured 窗口内成功 1KB 对象的数据面端到端传输时延。
- 使用 PUT 操作衡量对象传输能力（写入本地 slab + RDMA 异步复制）。
- 失败样本单独计数，不混入成功样本分位数。
- 不统计构建、脚本启动、环境启动和 warmup 时间。
