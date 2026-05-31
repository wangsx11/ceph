# Automated Function/Performance Focus Pipeline

You are running in a fresh non-interactive Codex exec session.

Repository root: /home/wangshouxin/native-rdma-web
Pipeline dir: /home/wangshouxin/native-rdma-web/.ai/function_perf_pipeline
Round: 4

Important:
- Do not assume prior chat history.
- The older .ai/pipeline/DONE is historical only; do not treat it as current acceptance.
- Read the local files listed below.
- Keep context compact by relying on files, not chat memory.
- Preserve unrelated user changes in the dirty working tree.
- If blocked, create /home/wangshouxin/native-rdma-web/.ai/function_perf_pipeline/BLOCKED with a short reason.
- Do not create /home/wangshouxin/native-rdma-web/.ai/function_perf_pipeline/DONE except in Round 5 after focused acceptance passes.

Required pipeline files:
- /home/wangshouxin/native-rdma-web/.ai/function_perf_pipeline/plan.md
- /home/wangshouxin/native-rdma-web/.ai/function_perf_pipeline/state.md

Previous focused reports, if present:
- /home/wangshouxin/native-rdma-web/.ai/function_perf_pipeline/reports/round-01.md
- /home/wangshouxin/native-rdma-web/.ai/function_perf_pipeline/reports/round-02.md
- /home/wangshouxin/native-rdma-web/.ai/function_perf_pipeline/reports/round-03.md

Round-specific instructions:

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

End-of-round requirements:
- Update /home/wangshouxin/native-rdma-web/.ai/function_perf_pipeline/state.md.
- Mention changed files and validation commands in the final response.
- Keep the final response concise enough for the next round to read.
- If you cannot continue safely, write /home/wangshouxin/native-rdma-web/.ai/function_perf_pipeline/BLOCKED; otherwise leave it absent.
