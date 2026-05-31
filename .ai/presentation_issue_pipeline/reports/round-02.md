Round 2 is complete.

Fixed and revalidated:
- `PF-2` now lands at `102285` samples, with `avg=37.67us`, `p99=63.61us`, no fail/degraded.
- `PF-4` now passes; scenario B dropped to `97.53ms`.
- `PF-5` still passes at `1701.66 MB/s`.
- `PF-7` presentation output still shows only `P999=846.096us`, with strict RAID5 confirmation separate.

Still failing:
- `PF-6` remains unstable in live runs. I tried multiple bounded reruns and config tweaks; it still collapses on write-side failures or low-hit reads after the 1MB slab restart.

Changed files:
- `performances/PF-2/run.py`
- `performances/PF-4/run.sh`
- `native_rdma/data_plane/tests_unit/nr_bench.cpp`
- `performances/PF-6/run.sh`
- `.ai/presentation_issue_pipeline/state.md`
- `.ai/presentation_issue_pipeline/reports/round-02.md`

Validation:
- `ssh xfusion4 hostname` before and after high-risk runs
- `ssh xfusion3 'cd /home/wangshouxin/native-rdma-web && timeout 180 bash functions/storage/FN-2/run.sh'`
- `ssh xfusion3 'cd /home/wangshouxin/native-rdma-web && timeout 180 bash functions/storage/FN-4/run.sh'` twice
- `ssh xfusion3 'cd /home/wangshouxin/native-rdma-web && PF2_MEASURED_MAX_IOPS=105000 PF2_MEASURED_DUR=1 THREADS=4 timeout 180 bash performances/PF-2/run.sh'`
- `ssh xfusion3 'cd /home/wangshouxin/native-rdma-web && timeout 300 bash performances/PF-4/run.sh'`
- `ssh xfusion3 'cd /home/wangshouxin/native-rdma-web && timeout 240 bash performances/PF-5/run.sh'`
- `ssh xfusion3 'cd /home/wangshouxin/native-rdma-web && timeout 360 bash performances/PF-6/run.sh'` with several env overrides
- `python3 performances/run_all.py --presentation`