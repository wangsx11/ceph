# PF-7 Summary

- Metric: 仿真引擎定期备份存储能力
- Source: `docs/性能要求.md` 第 7 条
- Generated At: 2026-05-04T01:59:12+0800
- Key Result: p999=739.499us, raid5_confirmed=True
- Threshold: 3+1 RAID5 系统下 4KB 写入 P999 <= 1ms
- Result: PASS
- Result Dir: /home/wangshouxin/native-rdma-web/performances/PF-7
- Raw JSON: /home/wangshouxin/native-rdma-web/performances/PF-7/raw.json
- Raw CSV: 未生成
- Run Log: /home/wangshouxin/native-rdma-web/performances/PF-7/logs/run.log

## 关键统计值

| Key | Value |
|---|---:|
| `backend` | dataplane |
| `lat_p50_us` | 20.65 |
| `lat_p95_us` | 23.654 |
| `lat_p99_us` | 88.586 |
| `lat_p999_us` | 739.499 |
| `lat_max_us` | 22534.476 |
| `success_writes` | 1294522 |
| `failed_writes` | 0 |
| `client_iops` | 21575.35 |
| `raid5_confirmed` | True |
| `rw` | sequential-ring-pwrite |
| `direct` | data-plane-file-writer |
| `fsync` | True |
| `queue_depth` | 1 |
| `threads` | 1 |
| `duration_s` | 60 |
| `fio_exit_code` | N/A |
| `fio_job_error` | N/A |

## 统计口径

- 默认后端为 `dataplane`：脚本通过 UDS 调用数据面的 `RPC_BACKUP_WRITE`，统计数据面内部 4KB 备份写完成耗时。
- `PF7_BACKEND=fio` 可切换为 fio 直写路径，用于存储设备对照测试。
- P999 按成功写入请求完成延迟样本计算；失败请求不参与分位数，单独计入 `failed_writes`。
- 未设置 `RAID5_CONFIRMED=1` 前，结果不能作为严格 3+1 RAID5 验收通过依据。
