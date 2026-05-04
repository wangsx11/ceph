# PF-2 Summary

- Metric: RDMA 网络环境下对象传输能力
- Source: `docs/性能要求.md` 第 2 条
- Generated At: 2026-05-04T23:40:57+0800
- Samples: 0/100000
- Key Result: avg=0.0us, p99=0.0us
- Threshold: 平均时延 <= 50us；P99 <= 100us；样本数 >= 100,000
- Result: FAIL
- Result Dir: /home/wangshouxin/native-rdma-web/performances/PF-2/history/web_20260504_234044_pf_PF2_20260504_234044_057611d6
- Raw JSON: /home/wangshouxin/native-rdma-web/performances/PF-2/history/web_20260504_234044_pf_PF2_20260504_234044_057611d6/raw.json
- Run Log: /home/wangshouxin/native-rdma-web/performances/PF-2/history/web_20260504_234044_pf_PF2_20260504_234044_057611d6/logs/run.log

## 关键统计值

| Key | Value |
|---|---:|
| `samples` | 0 |
| `lat_avg_us` | 0.0 |
| `lat_p50_us` | 0.0 |
| `lat_p99_us` | 0.0 |
| `lat_p99_9_us` | 0.0 |
| `lat_max_us` | 0.0 |
| `ops_fail` | 482481 |
| `ops_degraded` | 2 |

## 统计口径

- 统计 measured 窗口内成功 1KB 对象的数据面端到端传输时延。
- 使用 PUT 操作衡量对象传输能力（写入本地 slab + RDMA 异步复制）。
- 失败样本单独计数，不混入成功样本分位数。
- 不统计构建、脚本启动、环境启动和 warmup 时间。
