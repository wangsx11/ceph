# Round 1: Safe Current-State Diagnosis

You are Round 1 of the focused function/performance pipeline. This is a fresh
non-interactive Codex exec session.

## Objective

Determine the current failing function and performance points without causing a
slow or SSH-disruptive run. Focus especially on:

- function suite stability;
- RDMA FN-4 CPU/GPU high-speed direct access;
- performance panels that do not pass;
- performance commands that may interrupt SSH.

## Required Reading

Read:

- `.ai/function_perf_pipeline/plan.md`
- `.ai/function_perf_pipeline/state.md`
- `docs/project-onboarding-skill/SKILL.md`
- `docs/功能要求.md`
- `docs/性能要求.md`
- `functions/rdma/FN-4/FN-4.md`
- `functions/rdma/FN-4/summary.md`
- latest relevant `functions/**/summary.md`
- latest relevant `performances/PF-*/summary.md`
- latest relevant `performances/PF-*/raw.json`
- `.ai/pipeline/state.md` and old reports as historical evidence only.

## Checks

Prefer inspection and short targeted probes first. Do not immediately run the
full unrestricted `performances/run_all.sh`.

Perform safe diagnostics:

- inspect performance scripts for duration, traffic volume, and environment
  knobs;
- identify currently non-passing PF items from raw/summary files;
- inspect FN-4 runner and current raw/summary status;
- verify non-invasive GDR prerequisites on `xfusion4` if possible:
  `nvidia-smi`, peer-memory module, CUDA compiler/runtime, RDMA device;
- check whether `ssh xfusion4 hostname` is stable before/after any risky probe.

Only run heavy commands if you first add timeouts and SSH probes.

## Required Output

Update `.ai/function_perf_pipeline/state.md` with:

- current function failures or risks;
- current performance failures;
- whether FN-4 is a real failure, environment issue, or runner/summary issue;
- which commands are too slow or SSH-risky;
- exact repair priorities for Round 2 and Round 3.

If safe continuation is impossible, create `.ai/function_perf_pipeline/BLOCKED`.

Your final response will be saved as
`.ai/function_perf_pipeline/reports/round-01.md`.
