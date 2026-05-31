# Round 5: Final Focused Acceptance

You are Round 5 of the focused function/performance pipeline. This is a fresh
non-interactive Codex exec session.

## Objective

Perform the final focused acceptance run. Create
`.ai/function_perf_pipeline/DONE` only if all focused requirements pass.

## Required Reading

Read:

- `.ai/function_perf_pipeline/plan.md`
- `.ai/function_perf_pipeline/state.md`
- reports from Rounds 1-4.

## Final Checks

Run the final flow from a clean practical state:

1. Start `native_rdma` in the required mode.
2. Run the function suite twice consecutively.
3. Explicitly validate FN-4 CPU/GPU high-speed direct access.
4. Run the performance presentation-safe path.
5. Verify the relevant dashboard summaries/panels.
6. Verify SSH remains stable before, during, and after performance checks.

## Pass Criteria

Create `.ai/function_perf_pipeline/DONE` only if:

- both consecutive function runs pass or have precisely documented acceptable
  hardware-only waivers;
- FN-4 is either truly passed on the GDR path or honestly documented as blocked
  by hardware/environment, not mislabeled;
- all intended performance presentation panels pass;
- no performance command in the final path breaks SSH;
- final reports and summaries reflect actual current results.

If any criterion fails, do not create `DONE`. Create
`.ai/function_perf_pipeline/BLOCKED` and update state with exact remaining work.

## Required Output

Update `.ai/function_perf_pipeline/state.md` with final status, commands,
results, changed files, and residual risks.

Your final response will be saved as
`.ai/function_perf_pipeline/reports/round-05.md`.
