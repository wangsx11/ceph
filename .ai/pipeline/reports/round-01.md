**Round 1 Diagnosis Complete**

Updated [state.md](/home/wangshouxin/native-rdma-web/.ai/pipeline/state.md). `BLOCKED` and `DONE` are absent.

Key findings:
- Direct sandbox entrypoints fail because `/dev/infiniband` is hidden: `start.sh` exit 2, `functions/run_all.sh` exit 1, `performances/run_all.sh` exit 2.
- Host-side startup through `ssh xfusion3` succeeds; `/`, `/function-dashboard/`, and `/performance-dashboard/` return 200 and cluster status is RDMA-connected.
- Demo 3, 5, and 6 API flows pass, but Demo 5 does not cover PF-1 strict bandwidth utilization.
- Host function suite: 12 PASS, 3 FAIL, 1 SKIP, 1 WAIVED. Failures are `rdma/FN-3`, `rdma/FN-5`, `mempool/FN-4`, all around peer readback/visibility.
- Host performance suite: 5/9 PASS, exit 1, elapsed 410s. Failures: `PF-1`, `PF-3`, `PF-4`, `PF-6`. SSH to `xfusion4` stayed stable for all 40 probes.
- Evidence issues found: stale `performances/summary.md`, summary APIs showing fresh result data as `executed=false`/pending, stale dashboard README API paths, and some demo JS hardcoded localhost fallbacks.

Changed/generated files:
- Updated: `.ai/pipeline/state.md`
- Generated logs: `.ai/pipeline/logs/round1_*.log`
- Refreshed by test runs: `functions/**/raw.json`, `functions/**/summary.md`, `performances/PF-*/raw.json`, `performances/PF-*/summary.md`, and run logs.

Validation commands run included:
- `cd native_rdma && bash start.sh`
- `bash functions/run_all.sh`
- `bash performances/run_all.sh`
- Host-side `ssh xfusion3 'cd ... && bash start.sh'`
- Host-side `ssh xfusion3 'cd ... && bash functions/run_all.sh'`
- Host-side `ssh xfusion3 'cd ... && bash performances/run_all.sh'`
- Dashboard route/API curls and repeated `ssh xfusion4 hostname` probes.