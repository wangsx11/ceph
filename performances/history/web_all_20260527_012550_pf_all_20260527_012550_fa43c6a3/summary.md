# Performances Summary (2026-05-27T01:25:50+0800)

- Profile: presentation
- Passed: 9/9
- Result: PASS

| PF | Key Result | Result | Source |
|---|---|---:|---|
| PF-1 | 吞吐 1178586 ops/s，带宽利用率 59.06% | PASS | preserved_evidence |
| PF-2 | avg 34.68us，P99 47.35us | PASS | preserved_evidence |
| PF-3 | 提升 37.36% | PASS | preserved_evidence |
| PF-4 | A 152.3ms，B 94.02ms | PASS | preserved_evidence |
| PF-5 | 1388.54 MB/s | PASS | preserved_evidence |
| PF-6 | 写 10.826 GB/s，读 20.516 GB/s | PASS | preserved_evidence |
| PF-7 | P999 739.499us，RAID5 True | PASS | preserved_evidence |
| PF-8 | speedup 1.332x，events/s 133183 | PASS | preserved_evidence |
| PF-9 | 损失 0%，节省 11.47%，提升 41.36% | PASS | preserved_evidence |

## Profile Note

- Dashboard presentation mode is bounded and preserves existing PF evidence for a stable live flow.
- No heavy performance benchmark is rerun from the dashboard all-run path in this mode.
- Full validation remains `bash performances/run_all.sh` and is not replaced by this profile.
