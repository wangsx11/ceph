# Function And Performance Focused Pipeline Plan

## Target

Fix and validate the currently problematic function and performance areas:

1. Performance tests must not run too slowly for the presentation path.
2. Performance tests must not send enough traffic to break SSH connectivity.
3. Performance panels that currently fail must be identified and fixed.
4. Function checks must pass twice consecutively.
5. RDMA FN-4 CPU/GPU high-speed direct access must be rechecked and fixed if
   the current implementation, runner, environment detection, or summary is
   wrong.

## Required Reading Every Round

- `docs/project-onboarding-skill/SKILL.md`
- `.ai/function_perf_pipeline/plan.md`
- `.ai/function_perf_pipeline/state.md`
- `docs/功能要求.md`
- `docs/性能要求.md`
- `docs/function_dashboard验证与实现文案.md`
- `docs/performance_dashboard验证与实现文案.md`
- `functions/rdma/FN-4/FN-4.md`
- `functions/rdma/FN-4/summary.md`

Historical evidence to read but not blindly trust:

- `.ai/pipeline/state.md`
- `.ai/pipeline/reports/round-01.md`
- `.ai/pipeline/reports/round-05.md`

## Safety Rules

- Do not run unrestricted high-traffic performance loops until the test script
  has been inspected and bounded.
- Run performance tests one item at a time when diagnosing.
- Wrap high-risk commands with `timeout`.
- Probe SSH before and after every high-risk command.
- If practical, run a background SSH probe loop against `xfusion4`.
- Stop performance execution if SSH probes fail repeatedly.
- Do not fabricate pass results.
- If a presentation-safe profile is introduced, preserve a distinct full/strict
  profile or document why it is not available.
- Presentation UI can stay clean, but internal docs/state must record tradeoffs.
- Preserve unrelated user changes.

## Hardware Execution Rule

Previous evidence showed direct Codex sandbox runs may not see `/dev/infiniband`.
For hardware validation, prefer host-side commands such as:

```bash
ssh xfusion3 'cd /home/wangshouxin/native-rdma-web && <command>'
```

Direct local commands may still be used for source inspection, syntax checks,
and non-hardware logic.

## Rounds

### Round 1: Safe Current-State Diagnosis

Read current raw files, summaries, old reports, and source. Diagnose which
function/performance items are currently failing, with special attention to
FN-4 and SSH instability. Avoid full unrestricted performance runs.

### Round 2: Function And FN-4 Repair

Fix function-suite issues and FN-4 CPU/GPU high-speed direct access detection,
startup mode, runner, evidence, or summary problems. Validate function checks
twice consecutively if safe.

### Round 3: Performance Stabilization

Fix failing performance points and redesign the presentation-safe performance
path so it is bounded, not too slow, and does not destabilize SSH. Preserve
strict/full evidence paths where possible.

### Round 4: Consecutive Validation

Run the function suite twice consecutively, explicitly validate FN-4, and run
the performance presentation path with SSH probes. Fix remaining failures.

### Round 5: Final Focused Acceptance

Cold start, run function twice, run FN-4, run the performance presentation path,
verify dashboards/summaries, and create `DONE` only if the focused target passes
without SSH instability.
