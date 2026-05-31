# Performances Summary (2026-05-29T12:12:43+0800)

- Profile: presentation
- Passed: 8/9
- Result: FAIL

| PF | Metric | Key Result | Result | Exit Code |
|---|---|---|---:|---:|
| PF-1 | `perf_01` | 1704175 ops/s, util=59.21% | PASS | 0 |
| PF-2 | `perf_02_latency` | avg=37.61us, p99=66.55us | PASS | 0 |
| PF-3 | `perf_03_qos` | gain=81.81% | PASS | 0 |
| PF-4 | `perf_04_batch_latency` | A=124.45ms, B=92.23ms | PASS | 0 |
| PF-5 | `perf_05_batch_bw` | 1601.84 MB/s | PASS | 0 |
| PF-6 | `perf_06_tier_bw` | write=0 GB/s, read=0.002 GB/s | FAIL | 1 |
| PF-7 | `perf_07_backup_latency` | P999=846.096us | PASS | 0 |
| PF-8 | `perf_08_simulation` | speedup=1.276x | PASS | 0 |
| PF-9 | `perf_09_mempool` | overhead=0%, savings=11.47%, scale=33.3% | PASS | 0 |

## Result Files
- PF-1: `/home/wangshouxin/native-rdma-web/performances/PF-1/summary.md` / `/home/wangshouxin/native-rdma-web/performances/PF-1/raw.json`
- PF-2: `/home/wangshouxin/native-rdma-web/performances/PF-2/summary.md` / `/home/wangshouxin/native-rdma-web/performances/PF-2/raw.json`
- PF-3: `/home/wangshouxin/native-rdma-web/performances/PF-3/summary.md` / `/home/wangshouxin/native-rdma-web/performances/PF-3/raw.json`
- PF-4: `/home/wangshouxin/native-rdma-web/performances/PF-4/summary.md` / `/home/wangshouxin/native-rdma-web/performances/PF-4/raw.json`
- PF-5: `/home/wangshouxin/native-rdma-web/performances/PF-5/summary.md` / `/home/wangshouxin/native-rdma-web/performances/PF-5/raw.json`
- PF-6: `/home/wangshouxin/native-rdma-web/performances/PF-6/summary.md` / `/home/wangshouxin/native-rdma-web/performances/PF-6/raw.json`
- PF-7: `/home/wangshouxin/native-rdma-web/performances/PF-7/summary.md` / `/home/wangshouxin/native-rdma-web/performances/PF-7/raw.json`
- PF-8: `/home/wangshouxin/native-rdma-web/performances/PF-8/summary.md` / `/home/wangshouxin/native-rdma-web/performances/PF-8/raw.json`
- PF-9: `/home/wangshouxin/native-rdma-web/performances/PF-9/summary.md` / `/home/wangshouxin/native-rdma-web/performances/PF-9/raw.json`

## Notes
- PF-6: LOW HIT RATIO 0.0000: GETs mostly missed
