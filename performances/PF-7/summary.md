# PF-7 Summary

- Metric: 仿真引擎定期备份存储能力
- Source: `docs/性能要求.md` 第 7 条
- Generated At: 2026-05-04T00:23:25+0800
- Key Result: p999=21.376us, raid5_confirmed=False
- Threshold: 3+1 RAID5 系统下 4KB 写入 P999 <= 1ms
- Result: PASS
- Result Dir: /home/wangshouxin/native-rdma-web/performances/PF-7
- Raw JSON: /home/wangshouxin/native-rdma-web/performances/PF-7/raw.json
- Raw CSV: 未生成
- Run Log: /home/wangshouxin/native-rdma-web/performances/PF-7/logs/run.log

## 关键统计值

| Key | Value |
|---|---:|
| `lat_p50_us` | 14.144 |
| `lat_p95_us` | 15.296 |
| `lat_p99_us` | 17.024 |
| `lat_p999_us` | 21.376 |
| `lat_max_us` | 1650.667 |
| `success_writes` | 3489814 |
| `raid5_confirmed` | False |
| `rw` | randwrite |
| `direct` | 1 |
| `fsync` | False |
| `queue_depth` | 1 |
| `threads` | 1 |
| `duration_s` | 60 |
| `fio_exit_code` | -6 |
| `fio_job_error` | 0 |

## 统计口径

- 该指标在旧 `native_rdma/tests/performance/` 下没有脚本，本 `run.py` 新增 fio 4KB 写延迟测试。
- P999 按成功写入请求完成延迟样本计算。
- 未设置 `RAID5_CONFIRMED=1` 前，结果不能作为严格 3+1 RAID5 验收通过依据。

## 说明

RAID5_CONFIRMED is not set to 1; latency was measured, but this cannot be accepted as strict 3+1 RAID5 validation. fio process exited with -6 after emitting JSON; fio job error=0.
