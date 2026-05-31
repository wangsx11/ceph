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
