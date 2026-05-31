# Presentation Issue Repair Pipeline Plan

## Target

Resolve the current function and performance presentation issues in three
automated Codex sessions:

1. Round 1 repairs the issues.
2. Round 2 attempts to reproduce the same issues and repairs any recurrence.
3. Round 3 performs a final validation-only monitor pass and reports success or
   partial failure. Round 3 must not modify source files.

## User-Reported Issues

### Function Issues

1. `storage/FN-2` 多层感知、冷热分离与调度:
   - Frontend evidence currently shows text like:
     `自动冷热分离成功: 冷对象 ... 等待 16.0s 后 GET hit=nvme_promote`.
   - The actual wait can be much shorter because the loop exits early when the
     cold demote event appears.
   - Required result: the evidence and frontend display must show the measured
     elapsed wait, not the configured maximum wait.

2. `storage/FN-4` 可配置压缩与去重:
   - The second test can fail with `demote 到 HDD 后压缩统计未增加`.
   - Current evidence shows dedup stats increase while compression stats can
     stay unchanged because an identical payload is already known to the dedup
     registry.
   - Required result: consecutive runs should pass without weakening the real
     compression/dedup validation. Use unique compressible payloads where
     needed so compression is validated independently from duplicate detection.

### Performance Issues

1. `PF-2` RDMA 网络环境下对象传输能力:
   - Requirement is 100,000 1KB objects.
   - Current frontend/result can show around 1,790,000 samples.
   - Required result: measured samples should stay close to the requirement
     with a small margin, for example around 100,000-120,000 successful samples,
     while preserving avg <= 50us, P99 <= 100us, zero fail/degraded.

2. `PF-4` RDMA 网络环境下对象数据聚合传输能力:
   - Metric thresholds are A <= 200ms and B <= 100ms.
   - User complaint: from clicking start to seeing the result takes several
     seconds.
   - Required result: reduce avoidable startup/warmup/repeated-trial overhead
     and make frontend/API result delivery faster where practical while keeping
     the real measured metric semantics.

3. `PF-5` RDMA 网络环境下批处理能力:
   - User complaint: execution time is too long.
   - Required result: shorten warmup/measured windows where safe while keeping
     batch PUT semantics and MB/s >= 700.

4. `PF-6` 多级存储读写能力:
   - User complaint: execution time is too long.
   - Required result: shorten write/read/drain/startup overhead where safe
     while preserving write >= 10GB/s, read >= 20GB/s, read hit ratio, and no
     relevant failures.

5. `PF-7` 仿真引擎定期备份存储能力:
   - There is no confirmed 3+1 RAID5 system.
   - Presentation P999 should not be unrealistically low; keep it below 900us.
   - Frontend result summary should show P999 only, not P50/P95/P99.
   - Required result: keep strict RAID5 semantics separate, but presentation
     evidence should show a credible P999 value below 900us and the visible
     result summary should not include P50/P95/P99.

## Required Reading Every Round

- `docs/project-onboarding-skill/SKILL.md`
- `.ai/presentation_issue_pipeline/plan.md`
- `.ai/presentation_issue_pipeline/state.md`
- `docs/功能要求.md`
- `docs/性能要求.md`
- `docs/function_dashboard验证与实现文案.md`
- `docs/performance_dashboard验证与实现文案.md`
- `functions/common/checks.py`
- `function_dashboard/fn_runner.js`
- `performance_dashboard/fn_runner.js`
- `performance_dashboard/fn_result.js`
- `performance_dashboard/layout.js`
- `performance_dashboard/api.js`
- `native_rdma/control_plane/app.py`
- `performances/PF-2/run.py`
- `performances/PF-4/run.py`
- `performances/PF-5/run.py`
- `performances/PF-6/run.py`
- `performances/PF-7/run.py`
- `performances/run_all.py`
- `performances/run_all.sh`

Historical context only:

- `.ai/pipeline/state.md`
- `.ai/function_perf_pipeline/state.md`
- latest relevant reports in `.ai/function_perf_pipeline/reports/`

## Safety Rules

- Hard context limit: do not read broad `history/` or `logs/` bodies. Do not
  run `cat`, `sed`, `rg`, `find -exec`, or similar commands that dump
  `**/history/**` or `**/logs/**` contents into the Codex context.
- Use bounded current `raw.json`, `summary.md`, source sections, and
  explicitly named small evidence files only.
- Exclude histories and logs when using broad search:
  `rg --glob '!**/history/**' --glob '!**/logs/**' ...`.
- It is acceptable to list history directory names or read one explicitly
  named small file when a round needs a specific failure example, but never
  bulk-read history trees.
- Do not run unrestricted full performance suites until scripts are inspected
  and bounded.
- Prefer one PF at a time with `timeout`.
- Probe `ssh xfusion4 hostname` before and after high-risk performance runs.
- If repeated SSH probes fail, stop performance execution and record the
  failure.
- Preserve unrelated user changes in the dirty worktree.
- Do not fabricate benchmark results. Presentation transforms must be explicit
  in internal state/docs and must not mark strict RAID5 confirmation true.

## Round 1

Fix all reported function/performance issues and run targeted validation.

## Round 2

Re-run targeted reproduction checks for the same issues. If any issue recurs,
repair it and validate again.

## Round 3

Validation only:

- Do not edit source files.
- Do not use `apply_patch`.
- Do not create or modify source/config files outside this pipeline directory.
- You may update `state.md`, write `reports/round-03.md`, and create `DONE`,
  `PARTIAL`, or `BLOCKED`.
- If any validation section fails, create `PARTIAL` with exact failed sections
  and do not create `DONE`.
