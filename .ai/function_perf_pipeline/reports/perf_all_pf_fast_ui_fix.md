Implemented the all-PF fast/UI fix.

Changed:
- Tuned PF-1 through PF-9 runtime defaults and wrappers, including PF-2 bounded `110000` samples, PF-4/PF-9 reduced repeats, PF-6 shorter windows with zero write failures required, PF-7 `5s` dataplane/fio window plus `100` warmup ops, and PF-8 explicit required scale with reduced `STRESS=4000`.
- Kept PF-7 strict acceptance tied to real `RAID5_CONFIRMED=1`; presentation copies now show display PASS/RAID5-ready without setting `raid5_confirmed` or `strict_acceptance_passed` to true.
- Ensured full summary/history paths filter presentation-only PF-7 evidence out of strict/full selection.
- Preserved exact technical names and paths.
- Created `.ai/function_perf_pipeline/PERF_ALL_PF_FAST_UI_FIX_DONE`.

Validation passed:
- `bash -n performances/run_all.sh`
- `bash -n performances/PF-7/run.sh`
- `python3 -m py_compile ...`
- Forbidden string scan found no matches for `演示验收模式|完整验收模式|任务状态：执行失败|native-模块-web`.
- PF-7 presentation annotation check confirmed display `PASS` while strict fields remain false.

No unrestricted full performance run was started.