# PF-2 Summary

- Metric: RDMA 网络环境下对象传输能力
- Source: `docs/性能要求.md` 第 2 条
- Generated At: 2026-05-05T06:29:41+0800
- Samples: 2224097/100000
- Key Result: avg=35.38us, p99=49.39us
- Threshold: 平均时延 <= 50us；P99 <= 100us；样本数 >= 100,000
- Result: PASS
- Result Dir: /home/wangshouxin/native-rdma-web/performances/PF-2/history/web_20260505_062928_pf_PF2_20260505_062928_c991f78e
- Raw JSON: /home/wangshouxin/native-rdma-web/performances/PF-2/history/web_20260505_062928_pf_PF2_20260505_062928_c991f78e/raw.json
- Run Log: /home/wangshouxin/native-rdma-web/performances/PF-2/history/web_20260505_062928_pf_PF2_20260505_062928_c991f78e/logs/run.log

## 关键统计值

| Key | Value |
|---|---:|
| `samples` | 2224097 |
| `lat_avg_us` | 35.38 |
| `lat_p50_us` | 31.74 |
| `lat_p99_us` | 49.39 |
| `lat_p99_9_us` | 71.2 |
| `lat_max_us` | 29111.08 |
| `ops_fail` | 0 |
| `ops_degraded` | 0 |

## 统计口径

- 统计 measured 窗口内成功 1KB 对象的数据面端到端传输时延。
- 使用 PUT 操作衡量对象传输能力（写入本地 slab + RDMA 异步复制）。
- 失败样本单独计数，不混入成功样本分位数。
- 不统计构建、脚本启动、环境启动和 warmup 时间。
