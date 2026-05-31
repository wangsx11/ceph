# PF-2 Summary

- Metric: RDMA 网络环境下对象传输能力
- Source: `docs/性能要求.md` 第 2 条
- Generated At: 2026-05-27T10:02:21+0800
- Samples: 1964444/100000
- Key Result: avg=40.16us, p99=66.64us
- Threshold: 平均时延 <= 50us；P99 <= 100us；样本数 >= 100,000
- Result: PASS
- Result Dir: /home/wangshouxin/native-rdma-web/performances/PF-2/history/web_20260527_100207_pf_PF2_20260527_100207_c4409f54
- Raw JSON: /home/wangshouxin/native-rdma-web/performances/PF-2/history/web_20260527_100207_pf_PF2_20260527_100207_c4409f54/raw.json
- Run Log: /home/wangshouxin/native-rdma-web/performances/PF-2/history/web_20260527_100207_pf_PF2_20260527_100207_c4409f54/logs/run.log

## 关键统计值

| Key | Value |
|---|---:|
| `samples` | 1964444 |
| `lat_avg_us` | 40.16 |
| `lat_p50_us` | 31.02 |
| `lat_p99_us` | 66.64 |
| `lat_p99_9_us` | 956.55 |
| `lat_max_us` | 39362.16 |
| `ops_fail` | 0 |
| `ops_degraded` | 0 |
| `max_iops` | 300000 |

## 统计口径

- 统计 measured 窗口内成功 1KB 对象的数据面端到端传输时延。
- 使用 PUT 操作衡量对象传输能力（写入本地 slab + 同步等待 RDMA WRITE 完成）。
- 失败样本单独计数，不混入成功样本分位数。
- 不统计构建、脚本启动、环境启动和 warmup 时间。
