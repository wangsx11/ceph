**Round 2 Complete**

Changed files:
- `.ai/function_perf_pipeline/state.md`
- `functions/run_all.py`
- `functions/common/checks.py`
- `functions/common/runner.py`
- Updated generated evidence: `functions/raw.json`, `functions/summary.md`, `functions/rdma/FN-4/*`, `functions/rdma/FN-5/*`, new `functions/logs/run_all_*`

Key fixes:
- Full function suite now runs RDMA FN-4 in explicit GDR mode and restores normal RDMA mode afterward.
- FN-4 no longer treats “hardware present but GDR not started/built” as a waiver; that is now a failure. WAIVED is no longer serialized/counts as `passed=true`.
- Function aggregate PASS now requires zero `FAIL`, `SKIP`, and `WAIVED`.
- Stabilized RDMA FN-5 by waiting briefly for RDMA route metadata visibility before peer readback.

Validation run:
- `timeout 420 ssh xfusion3 'cd /home/wangshouxin/native-rdma-web && LOCAL_HOST=xfusion3 NR_GDR_ENABLE=1 NR_TRANSPORT=rdma NR_ASYNC_REPL=0 bash native_rdma/start.sh'`
- `timeout 90 ssh xfusion3 'cd /home/wangshouxin/native-rdma-web && REQUIRE_PEER=1 bash functions/rdma/FN-4/run.sh'`
- `timeout 45 ssh xfusion3 'cd /home/wangshouxin/native-rdma-web && REQUIRE_PEER=1 bash functions/rdma/FN-5/run.sh'`
- Two consecutive full runs:
  - `functions/logs/run_all_20260527_123445.log`: PASS, no FAIL/SKIP/WAIVED
  - `functions/logs/run_all_20260527_123633.log`: PASS, 17 PASS / 0 FAIL / 0 SKIP / 0 WAIVED
- `timeout 10 ssh xfusion4 hostname` passed before and after the suite sequence.
- `python3 -m py_compile functions/common/checks.py functions/common/runner.py functions/run_all.py native_rdma/control_plane/app.py`

FN-4 latest evidence:
- `functions/rdma/FN-4/summary.md`: `PASS / 完成`
- A wrote 4096B to B GPU MR via `gpudirect_rdma`, B CUDA kernel validated `mismatches=0`, A RDMA readback also `mismatches=0`.

`BLOCKED` is absent. `DONE` was not created. Round 3 still owns PF-3, PF-4, PF-6, PF-7 strict/performance issues.