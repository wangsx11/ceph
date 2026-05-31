# Automated Function/Performance Focus Pipeline

You are running in a fresh non-interactive Codex exec session.

Repository root: /home/wangshouxin/native-rdma-web
Pipeline dir: /home/wangshouxin/native-rdma-web/.ai/function_perf_pipeline
Round: 3

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

Round-specific instructions:

# Round 3: Performance Stabilization

You are Round 3 of the focused function/performance pipeline. This is a fresh
non-interactive Codex exec session.

## Objective

Fix failing performance panels and make the presentation performance path
bounded, not too slow, and safe for SSH connectivity.

## Required Reading

Read:

- `.ai/function_perf_pipeline/plan.md`
- `.ai/function_perf_pipeline/state.md`
- `.ai/function_perf_pipeline/reports/round-01.md`
- `.ai/function_perf_pipeline/reports/round-02.md`
- `docs/性能要求.md`
- `docs/performance_dashboard验证与实现文案.md`
- `performances/run_all.sh`
- relevant `performances/PF-*/run.sh`, `run.py`, `summary.md`, and `raw.json`
- performance dashboard runner/API code.

## Work Scope

Focus on:

- PF panels that currently fail;
- PF commands that are too slow;
- PF commands that can send too much traffic and break SSH;
- dashboard "run all" behavior;
- timeout/progress/failure reporting;
- preserving strict/full mode separately from presentation-safe mode if needed.

Do not run unrestricted full performance tests until you have inspected the
scripts and added a safe execution strategy.

## Safety Requirements

Before any high-risk performance command:

- run `ssh xfusion4 hostname`;
- use `timeout`;
- start or perform SSH probes around the run;
- stop further high-risk execution if probes repeatedly fail;
- record elapsed time and probe results.

Prefer one PF at a time. Do not saturate the network just to test whether SSH
breaks.

## Required Output

Update `.ai/function_perf_pipeline/state.md` with:

- performance changes;
- safe execution profile or command;
- strict/full profile status;
- validation performed;
- remaining risks for Round 4.

If safe continuation is impossible, create `.ai/function_perf_pipeline/BLOCKED`.

Your final response will be saved as
`.ai/function_perf_pipeline/reports/round-03.md`.

End-of-round requirements:
- Update /home/wangshouxin/native-rdma-web/.ai/function_perf_pipeline/state.md.
- Mention changed files and validation commands in the final response.
- Keep the final response concise enough for the next round to read.
- If you cannot continue safely, write /home/wangshouxin/native-rdma-web/.ai/function_perf_pipeline/BLOCKED; otherwise leave it absent.
