**Round 3 Complete**

Updated `.ai/function_perf_pipeline/state.md`. `BLOCKED` and `DONE` are absent.

Changed files:
- `performances/run_all.sh`
- `performances/run_all.py`
- `performances/PF-3/run.py`
- `performances/PF-4/run.py`
- `performances/PF-6/run.py`
- `performances/PF-7/run.py`
- `native_rdma/control_plane/app.py`
- Generated evidence under `performances/PF-3`, `PF-4`, `PF-6`, `PF-7`, plus `performances/summary.md` / `raw.json`

Key results:
- Added guarded full execution: per-PF timeout, xfusion4 SSH pre/during/post probes, elapsed logging, and early abort on repeated SSH probe failures.
- Added one-PF guarded execution via `PERFORMANCE_PF_LIST=PF-N bash performances/run_all.sh`.
- Preserved presentation-safe mode: `bash performances/run_all.sh --presentation` reruns no live PF load and restores the full aggregate afterward.
- PF-3 now PASS: `gain_pct=81.81`, zero fail/degraded.
- PF-4 now PASS: A `136.66ms`, B `94.57ms`.
- PF-6 now PASS: write `10.816 GB/s`, read `21.622 GB/s`.
- PF-7 latency passes but strict acceptance correctly FAILs until `RAID5_CONFIRMED=1`.

Validation commands:
- `bash -n performances/run_all.sh`
- `python3 -m py_compile performances/run_all.py performances/PF-3/run.py performances/PF-4/run.py performances/PF-6/run.py performances/PF-7/run.py native_rdma/control_plane/app.py`
- `timeout 60 bash performances/run_all.sh --presentation`
- `timeout 420 ssh xfusion3 'cd /home/wangshouxin/native-rdma-web && PERFORMANCE_PF_LIST=PF-3 PERF_SSH_PROBE_INTERVAL_S=5 PERF_TIMEOUT_PF_3_S=180 bash performances/run_all.sh'`
- Same guarded form for `PF-4`, `PF-6`, and `PF-7`
- `curl http://127.0.0.1:5000/api/performance/presentation_summary`
- `curl http://127.0.0.1:5000/api/performance/summary`

Current full performance status: `8/9` strict PASS. Only PF-7 remains strict FAIL due missing RAID5 topology confirmation. All xfusion4 SSH probes around the live PF runs passed.