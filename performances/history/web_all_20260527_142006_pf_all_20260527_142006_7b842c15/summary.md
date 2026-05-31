# Performances Summary (2026-05-27T14:20:06+0800)

- Profile: presentation
- Passed: 9/9
- Result: PASS

| PF | Key Result | Result | Source |
|---|---|---:|---|
| PF-1 | 吞吐 1704175 ops/s，带宽利用率 59.21% | PASS | preserved_evidence |
| PF-2 | avg 40.37us，P99 60.62us | PASS | preserved_evidence |
| PF-3 | 提升 81.81% | PASS | preserved_evidence |
| PF-4 | A 136.66ms，B 94.57ms | PASS | preserved_evidence |
| PF-5 | 1742.91 MB/s | PASS | preserved_evidence |
| PF-6 | 写 10.816 GB/s，读 21.622 GB/s | PASS | preserved_evidence |
| PF-7 | P999 26.096us，RAID5 展示就绪，严格RAID5 False，严格验收待确认 | PASS (presentation latency, RAID5 strict unconfirmed) | preserved_evidence |
| PF-8 | speedup 1.276x，events/s 127571 | PASS | preserved_evidence |
| PF-9 | 损失 0%，节省 11.47%，提升 33.3% | PASS | preserved_evidence |

## Profile Note

- Dashboard presentation mode is bounded and preserves existing PF evidence for a stable live flow.
- No heavy performance benchmark is rerun from the dashboard all-run path in this mode.
- Full validation remains `bash performances/run_all.sh` and is not replaced by this profile.
