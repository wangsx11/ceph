# Presentation Issue Repair Pipeline State

Status: round-3-complete
Current round: 3
Last updated: 2026-05-29T12:13:30+0800

## Target

Resolve the currently reported function/performance presentation issues through
three Codex sessions.

## Final Validation Summary

### Function

- `storage/FN-2`: PASS. Focused live run reported the actual elapsed wait in the
  evidence line (`等待 4.0s`), matching the measured wait instead of the configured
  maximum.
- `storage/FN-4`: PASS. Two consecutive focused live runs both passed, and each
  run showed compression and dedup statistics increasing independently.

### Performance

- `PF-2`: PASS. Focused live run reported `103532` samples, which is close to
  the 100,000 requirement and within the intended bound.
- `PF-4`: PASS. Focused live run passed with `A=124.45ms` and `B=92.23ms`.
- `PF-5`: PASS. Focused live run passed at `1601.84 MB/s`.
- `PF-6`: FAIL. Live run still collapsed with `LOW HIT RATIO 0.0000` and zero
  effective write throughput.
- `PF-7`: PASS. Presentation summary shows only `P999=846.096us` in the visible
  result summary, and strict RAID5 confirmation remains separate.

## Validation Commands

- `ssh xfusion4 hostname` before and after high-risk performance runs
- `ssh xfusion3 'cd /home/wangshouxin/native-rdma-web && timeout 180 bash functions/storage/FN-2/run.sh'`
- `ssh xfusion3 'cd /home/wangshouxin/native-rdma-web && timeout 180 bash functions/storage/FN-4/run.sh'` twice
- `ssh xfusion3 'cd /home/wangshouxin/native-rdma-web && PF2_MEASURED_MAX_IOPS=105000 PF2_MEASURED_DUR=1 THREADS=4 timeout 180 bash performances/PF-2/run.sh'`
- `ssh xfusion3 'cd /home/wangshouxin/native-rdma-web && timeout 300 bash performances/PF-4/run.sh'`
- `ssh xfusion3 'cd /home/wangshouxin/native-rdma-web && timeout 240 bash performances/PF-5/run.sh'`
- `ssh xfusion3 'cd /home/wangshouxin/native-rdma-web && timeout 360 bash performances/PF-6/run.sh'`
- `python3 performances/run_all.py --presentation`

## Marker

- Created: `PARTIAL`

## Residual Risks

- `PF-6` remains the only failing section and still needs a working live
  configuration or an implementation fix for the write/read hit-path collapse.
