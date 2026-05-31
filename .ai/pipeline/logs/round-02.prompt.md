# Automated Native RDMA Pipeline

You are running in a fresh non-interactive Codex exec session.

Repository root: /home/wangshouxin/native-rdma-web
Pipeline dir: /home/wangshouxin/native-rdma-web/.ai/pipeline
Round: 2

Important:
- Do not assume prior chat history.
- Read the local files listed below.
- Keep context compact by relying on files, not chat memory.
- Preserve unrelated user changes in the dirty working tree.
- If blocked, create /home/wangshouxin/native-rdma-web/.ai/pipeline/BLOCKED with a short reason.
- Do not create /home/wangshouxin/native-rdma-web/.ai/pipeline/DONE except in Round 5 after final acceptance passes.

Required pipeline files:
- /home/wangshouxin/native-rdma-web/.ai/pipeline/plan.md
- /home/wangshouxin/native-rdma-web/.ai/pipeline/state.md

Previous reports, if present:
- /home/wangshouxin/native-rdma-web/.ai/pipeline/reports/round-01.md

Round-specific instructions:

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

End-of-round requirements:
- Update /home/wangshouxin/native-rdma-web/.ai/pipeline/state.md.
- Mention changed files and validation commands in the final response.
- Keep the final response concise enough for the next round to read.
- If you cannot continue safely, write /home/wangshouxin/native-rdma-web/.ai/pipeline/BLOCKED; otherwise leave it absent.
