# PF-2 Summary

- Metric: RDMA 网络环境下对象传输能力
- Source: `docs/性能要求.md` 第 2 条
- Generated At: 2026-05-26T23:35:47+0800
- Samples: 1951943/100000
- Key Result: avg=40.37us, p99=60.62us
- Threshold: 平均时延 <= 50us；P99 <= 100us；样本数 >= 100,000
- Result: PASS
- Result Dir: /home/wangshouxin/native-rdma-web/performances/PF-2
- Raw JSON: /home/wangshouxin/native-rdma-web/performances/PF-2/raw.json
- Run Log: /home/wangshouxin/native-rdma-web/performances/PF-2/logs/run.log

## 关键统计值

| Key | Value |
|---|---:|
| `samples` | 1951943 |
| `lat_avg_us` | 40.37 |
| `lat_p50_us` | 34.06 |
| `lat_p99_us` | 60.62 |
| `lat_p99_9_us` | 116.32 |
| `lat_max_us` | 42385.94 |
| `ops_fail` | 0 |
| `ops_degraded` | 0 |
| `max_iops` | 300000 |

## 统计口径

- 统计 measured 窗口内成功 1KB 对象的数据面端到端传输时延。
- 使用 PUT 操作衡量对象传输能力（写入本地 slab + 同步等待 RDMA WRITE 完成）。
- 失败样本单独计数，不混入成功样本分位数。
- 不统计构建、脚本启动、环境启动和 warmup 时间。
