# Native RDMA Acceptance Pipeline Plan

## Final Target

Make the repository suitable for a presentation and acceptance flow:

1. Enter `native_rdma/`.
2. Run `bash start.sh`.
3. Open the function, performance, and demo frontends.
4. Run every intended function, performance, and demo item.
5. All items pass in one run.
6. The run does not cause visible network instability or SSH disconnects.

## Project Context To Read Every Round

Each round must begin by reading:

- `docs/project-onboarding-skill/SKILL.md`
- `docs/功能要求.md`
- `docs/性能要求.md`
- `docs/演示要求.md`
- `.ai/pipeline/state.md`

Read these when relevant:

- `docs/自研方案.md`
- `docs/功能指标拆分与functions目录需求.md`
- `docs/性能指标拆分与performances目录需求.md`
- `docs/function_dashboard验证与实现文案.md`
- `docs/performance_dashboard验证与实现文案.md`
- `docs/functions实现完成度.md`
- `docs/功能要求实现完整性检查.md`
- `docs/性能原始结果解读.md`
- `docs/硬件配置.md`

## Required Entrypoints

- Main startup: `cd native_rdma && bash start.sh`
- Function suite: `bash functions/run_all.sh`
- Performance suite: `bash performances/run_all.sh`
- Function frontend: `/function-dashboard/`
- Performance frontend: `/performance-dashboard/`
- Demo frontend: `/`

## Known Risks

- Some performance points, especially PF-1, may take too long for a live
  demonstration.
- PF-1 may stress networking enough to make SSH unstable.
- Some existing tests may pass without fully covering the written requirement.
- The final system needs both a presentation-friendly path and honest internal
  documentation of any unavoidable tradeoffs.

## Round Plan

### Round 1: Full Diagnosis

Run the existing startup, function, performance, and demo paths with monitoring.
Record command failures, long runtimes, network or SSH instability, frontend/API
failures, and coverage gaps. Avoid broad code changes.

### Round 2: Review And Initial Fixes

Review Round 1 conclusions. Separate true failures from false positives. Fix
obvious mistakes, wrong scripts, broken APIs, missing wiring, and incorrect
coverage mapping.

### Round 3: Presentation-Oriented Optimization

Optimize long-running or risky checks while preserving the most compliant
behavior possible. If a fully compliant presentation path is not practical,
implement the least noncompliant fallback, document it internally, and keep the
frontend presentation stable.

### Round 4: Complete Leftovers

Check what Round 3 left unfinished. Finish missing scripts, APIs, dashboard
behavior, evidence files, result summaries, and targeted regression tests.

### Round 5: Final Acceptance

Restart from `cd native_rdma && bash start.sh`, run all function, performance,
and demo paths, monitor network stability, and create `.ai/pipeline/DONE` only
if the final acceptance target is satisfied.

## Non-Negotiable Rules

- Do not fabricate benchmark results.
- Do not mark an item passed without evidence.
- Do not delete or revert user changes.
- Do not hide internal tradeoffs from documentation.
- Presentation UI does not need to expose internal compliance caveats, but the
  repository documentation must record them.
- Keep full and presentation-friendly modes distinguishable if both are needed.
- Prefer changes that preserve the real two-node RDMA flow over local-only
  simulation.
