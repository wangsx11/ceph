# PF-5 Summary

- Metric: RDMA 网络环境下批处理能力
- Source: `docs/性能要求.md` 第 5 条
- Generated At: 2026-05-04T00:21:27+0800
- Key Result: 1336.17 MB/s
- Threshold: 批处理传输速度 >= 700MB/s
- Result: PASS
- Result Dir: /home/wangshouxin/native-rdma-web/performances/PF-5
- Raw JSON: /home/wangshouxin/native-rdma-web/performances/PF-5/raw.json
- Run Log: /home/wangshouxin/native-rdma-web/performances/PF-5/logs/run.log

## 关键统计值

| Key | Value |
|---|---:|
| `mb_per_sec` | 1336.17 |
| `ops_per_sec` | 1304853.0 |
| `val_size` | 1024 |
| `threshold_mbs` | 700.0 |
| `ops_fail` | 0 |
| `ops_degraded` | 0 |

## 统计口径

- `mb_per_sec = ops_per_sec * val_size / 1,000,000`。
- 使用 batch PUT 模式提升吞吐。
- 不统计构建、脚本启动、环境启动和 warmup 时间。
