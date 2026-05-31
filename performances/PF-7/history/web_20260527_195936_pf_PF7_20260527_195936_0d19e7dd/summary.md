# PF-7 Summary

- Metric: 仿真引擎定期备份存储能力
- Source: `docs/性能要求.md` 第 7 条
- Generated At: 2026-05-27T20:00:38+0800
- Key Result: p999=23.535us, raid5_confirmed=False
- Threshold: 3+1 RAID5 系统下 4KB 写入 P999 <= 1ms
- Latency Result: PASS
- Strict Result: FAIL
- Result Dir: /home/wangshouxin/native-rdma-web/performances/PF-7/history/web_20260527_195936_pf_PF7_20260527_195936_0d19e7dd
- Raw JSON: /home/wangshouxin/native-rdma-web/performances/PF-7/history/web_20260527_195936_pf_PF7_20260527_195936_0d19e7dd/raw.json
- Raw CSV: 未生成
- Run Log: /home/wangshouxin/native-rdma-web/performances/PF-7/history/web_20260527_195936_pf_PF7_20260527_195936_0d19e7dd/logs/run.log

## 关键统计值

| Key | Value |
|---|---:|
| `backend` | dataplane |
| `lat_p50_us` | 4.652 |
| `lat_p95_us` | 8.153 |
| `lat_p99_us` | 12.204 |
| `lat_p999_us` | 23.535 |
| `lat_max_us` | 32849.648 |
| `success_writes` | 1897549 |
| `failed_writes` | 0 |
| `client_iops` | 31625.69 |
| `raid5_confirmed` | False |
| `rw` | sequential-ring-pwrite |
| `direct` | data-plane-file-writer |
| `fsync` | False |
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
- `passed` 表示自动化延迟子项通过；严格验收和脚本退出码以 `strict_acceptance_passed=true` 为准。

## 说明

RAID5_CONFIRMED is not set to 1; latency was measured through the data-plane backup writer, but strict 3+1 RAID5 topology still needs ops confirmation.
