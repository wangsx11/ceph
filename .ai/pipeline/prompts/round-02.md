# Round 2: Review And Initial Fixes

You are Round 2 of the native_rdma acceptance pipeline. This is an independent
Codex exec session. Do not assume chat history.

## Objective

Review Round 1's diagnosis, separate true issues from false positives, and fix
the most direct problems that block acceptance or later optimization.

## Required Reading

Read these first:

- `docs/project-onboarding-skill/SKILL.md`
- `.ai/pipeline/plan.md`
- `.ai/pipeline/state.md`
- `.ai/pipeline/reports/round-01.md`
- `docs/功能要求.md`
- `docs/性能要求.md`
- `docs/演示要求.md`

Then inspect the specific source files, scripts, dashboards, and docs implicated
by Round 1.

## Work Scope

Address issues such as:

- broken startup or stop behavior;
- dashboard route/API wiring failures;
- function/performance runner failures caused by script bugs;
- result files not being updated or read correctly;
- coverage mapping that is plainly wrong;
- missing low-risk tests or checks needed to prove a requirement.

Do not spend this round on large PF-1 or benchmark redesign unless a small,
obvious fix is available.

## Validation

Run targeted checks for every change. Prefer focused validation over full
performance reruns unless needed to confirm the fix.

## Required Output

Update `.ai/pipeline/state.md` with:

- Round 2 status;
- what Round 1 conclusions were confirmed or rejected;
- files changed;
- validation performed;
- remaining issues for Round 3.

If a condition prevents useful continuation, create `.ai/pipeline/BLOCKED` with
a short reason. Otherwise do not create `BLOCKED`.

Your final response will be saved as `.ai/pipeline/reports/round-02.md`; make it
a concise engineering report.
