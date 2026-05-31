# Automated Function/Performance Focus Pipeline

You are running in a fresh non-interactive Codex exec session.

Repository root: /home/wangshouxin/native-rdma-web
Pipeline dir: /home/wangshouxin/native-rdma-web/.ai/function_perf_pipeline
Round: 2

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

Round-specific instructions:

# Round 2: Function And FN-4 Repair

You are Round 2 of the focused function/performance pipeline. This is a fresh
non-interactive Codex exec session.

## Objective

Fix function-suite issues and the RDMA FN-4 CPU/GPU high-speed direct access
problem identified in Round 1.

## Required Reading

Read:

- `.ai/function_perf_pipeline/plan.md`
- `.ai/function_perf_pipeline/state.md`
- `.ai/function_perf_pipeline/reports/round-01.md`
- `docs/project-onboarding-skill/SKILL.md`
- `docs/功能要求.md`
- `functions/rdma/FN-4/FN-4.md`
- `functions/rdma/FN-4/summary.md`
- FN-4 source and runner files.

## Work Scope

Fix issues in:

- function runner mode handling;
- FN-4 GDR startup/environment detection;
- FN-4 runner evidence and summary generation;
- incorrect waiver/failure logic;
- function checks that are unstable across consecutive runs.

Do not fake GPUDirect. FN-4 passes only if the intended CPU-to-remote-GPU RDMA
path is validated. If hardware prerequisites are missing, document that
precisely and do not mark it as pass.

## Validation

Run targeted FN-4 validation in the correct host-side mode when possible, for
example:

```bash
ssh xfusion3 'cd /home/wangshouxin/native-rdma-web && LOCAL_HOST=xfusion3 NR_GDR_ENABLE=1 NR_TRANSPORT=rdma NR_ASYNC_REPL=0 bash native_rdma/start.sh'
ssh xfusion3 'cd /home/wangshouxin/native-rdma-web && REQUIRE_PEER=1 bash functions/rdma/FN-4/run.sh'
```

If Round 1 indicates it is safe, run the function suite twice consecutively:

```bash
ssh xfusion3 'cd /home/wangshouxin/native-rdma-web && bash functions/run_all.sh'
ssh xfusion3 'cd /home/wangshouxin/native-rdma-web && bash functions/run_all.sh'
```

Use the correct startup mode if the suite requires it.

## Required Output

Update `.ai/function_perf_pipeline/state.md` with:

- Round 2 changes;
- FN-4 result and evidence;
- two-run function-suite status, if run;
- remaining function issues for Round 4;
- performance issues left for Round 3.

If safe continuation is impossible, create `.ai/function_perf_pipeline/BLOCKED`.

Your final response will be saved as
`.ai/function_perf_pipeline/reports/round-02.md`.

End-of-round requirements:
- Update /home/wangshouxin/native-rdma-web/.ai/function_perf_pipeline/state.md.
- Mention changed files and validation commands in the final response.
- Keep the final response concise enough for the next round to read.
- If you cannot continue safely, write /home/wangshouxin/native-rdma-web/.ai/function_perf_pipeline/BLOCKED; otherwise leave it absent.
