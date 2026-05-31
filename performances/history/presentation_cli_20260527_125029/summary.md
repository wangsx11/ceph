# Performances Summary (2026-05-27T12:50:29+0800)

- Profile: presentation
- Passed: 9/9
- Result: PASS

| PF | Metric | Key Result | Result | Exit Code |
|---|---|---|---:|---:|
| PF-1 | `perf_01` | 1685217 ops/s, util=57.73% | PASS | 0 |
| PF-2 | `perf_02_latency` | avg=40.16us, p99=66.64us | PASS | 0 |
| PF-3 | `perf_03_qos` | gain=37.36% | PASS | 0 |
| PF-4 | `perf_04_batch_latency` | A=152.3ms, B=94.02ms | PASS | 0 |
| PF-5 | `perf_05_batch_bw` | 1388.54 MB/s | PASS | 0 |
| PF-6 | `perf_06_tier_bw` | write=10.826 GB/s, read=20.516 GB/s | PASS | 0 |
| PF-7 | `perf_07_backup_latency` | p999=739.499us, raid5=True | PASS | 0 |
| PF-8 | `perf_08_simulation` | speedup=1.332x | PASS | 0 |
| PF-9 | `perf_09_mempool` | overhead=0%, savings=11.47%, scale=41.36% | PASS | 0 |

## Result Files
- PF-1: `/home/wangshouxin/native-rdma-web/performances/PF-1/history/web_20260527_095822_pf_PF1_20260527_095822_c74fd391/summary.md` / `/home/wangshouxin/native-rdma-web/performances/PF-1/history/web_20260527_095822_pf_PF1_20260527_095822_c74fd391/raw.json`
- PF-2: `/home/wangshouxin/native-rdma-web/performances/PF-2/history/web_20260527_100207_pf_PF2_20260527_100207_c4409f54/summary.md` / `/home/wangshouxin/native-rdma-web/performances/PF-2/history/web_20260527_100207_pf_PF2_20260527_100207_c4409f54/raw.json`
- PF-3: `/home/wangshouxin/native-rdma-web/performances/PF-3/history/web_all_20260527_012749_pf_all_20260527_012749_a6888e84/summary.md` / `/home/wangshouxin/native-rdma-web/performances/PF-3/history/web_all_20260527_012749_pf_all_20260527_012749_a6888e84/raw.json`
- PF-4: `/home/wangshouxin/native-rdma-web/performances/PF-4/history/web_all_20260527_012749_pf_all_20260527_012749_a6888e84/summary.md` / `/home/wangshouxin/native-rdma-web/performances/PF-4/history/web_all_20260527_012749_pf_all_20260527_012749_a6888e84/raw.json`
- PF-5: `/home/wangshouxin/native-rdma-web/performances/PF-5/history/web_all_20260527_012749_pf_all_20260527_012749_a6888e84/summary.md` / `/home/wangshouxin/native-rdma-web/performances/PF-5/history/web_all_20260527_012749_pf_all_20260527_012749_a6888e84/raw.json`
- PF-6: `/home/wangshouxin/native-rdma-web/performances/PF-6/history/web_all_20260527_012749_pf_all_20260527_012749_a6888e84/summary.md` / `/home/wangshouxin/native-rdma-web/performances/PF-6/history/web_all_20260527_012749_pf_all_20260527_012749_a6888e84/raw.json`
- PF-7: `/home/wangshouxin/native-rdma-web/performances/PF-7/history/web_all_20260527_012749_pf_all_20260527_012749_a6888e84/summary.md` / `/home/wangshouxin/native-rdma-web/performances/PF-7/history/web_all_20260527_012749_pf_all_20260527_012749_a6888e84/raw.json`
- PF-8: `/home/wangshouxin/native-rdma-web/performances/PF-8/history/web_all_20260527_012749_pf_all_20260527_012749_a6888e84/summary.md` / `/home/wangshouxin/native-rdma-web/performances/PF-8/history/web_all_20260527_012749_pf_all_20260527_012749_a6888e84/raw.json`
- PF-9: `/home/wangshouxin/native-rdma-web/performances/PF-9/history/web_all_20260527_012749_pf_all_20260527_012749_a6888e84/summary.md` / `/home/wangshouxin/native-rdma-web/performances/PF-9/history/web_all_20260527_012749_pf_all_20260527_012749_a6888e84/raw.json`

## Profile Note

- This summary was generated for a presentation-safe profile.
- It does not replace `bash performances/run_all.sh` as full acceptance evidence.
- Rows marked as preserved evidence reuse existing `summary.md`/`raw.json` instead of rerunning heavy PFs live.
