# Round 4: Consecutive Validation

You are Round 4 of the focused function/performance pipeline. This is a fresh
non-interactive Codex exec session.

## Objective

Validate that function checks are stable across consecutive execution and that
the performance presentation path passes without SSH instability.

## Required Reading

Read:

- `.ai/function_perf_pipeline/plan.md`
- `.ai/function_perf_pipeline/state.md`
- reports from Rounds 1-3;
- relevant function and performance files changed in Rounds 2-3.

## Required Validation

Run or complete equivalent validation:

1. Start the required two-node stack in the correct mode.
2. Run the function suite twice consecutively.
3. Explicitly run or verify FN-4 CPU/GPU direct access.
4. Run the performance presentation path with SSH probes.
5. Confirm dashboard summaries reflect real current results.

Use timeouts and probes. If a command is unsafe, stop and record why instead of
continuing to stress the network.

## Fixes

Fix residual issues found during validation, but avoid broad unrelated refactors.

## Required Output

Update `.ai/function_perf_pipeline/state.md` with:

- first function run result;
- second function run result;
- FN-4 result;
- performance presentation result;
- SSH stability result;
- exact final checklist for Round 5.

If safe continuation is impossible, create `.ai/function_perf_pipeline/BLOCKED`.

Your final response will be saved as
`.ai/function_perf_pipeline/reports/round-04.md`.
