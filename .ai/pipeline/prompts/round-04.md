# Round 4: Complete Leftovers

You are Round 4 of the native_rdma acceptance pipeline. This is an independent
Codex exec session. Do not assume chat history.

## Objective

Finish all important leftovers from Rounds 1-3 and prepare the repository for
final acceptance.

## Required Reading

Read these first:

- `docs/project-onboarding-skill/SKILL.md`
- `.ai/pipeline/plan.md`
- `.ai/pipeline/state.md`
- `.ai/pipeline/reports/round-01.md`
- `.ai/pipeline/reports/round-02.md`
- `.ai/pipeline/reports/round-03.md`
- `docs/功能要求.md`
- `docs/性能要求.md`
- `docs/演示要求.md`

Then inspect all files listed as remaining issues in the state file.

## Work Scope

Complete:

- missed dashboard actions or API endpoints;
- incomplete function/performance result summaries;
- missing frontend status handling;
- missing docs for evidence or tradeoffs;
- scripts that still fail under the intended presentation flow;
- targeted test gaps that can be closed without destabilizing the system.

Avoid broad unrelated refactors.

## Validation

Run focused checks for each touched area. If practical, run a reduced complete
flow that approximates Round 5 without spending excessive time.

## Required Output

Update `.ai/pipeline/state.md` with:

- Round 4 status;
- files changed;
- validation performed;
- exact checklist for Round 5 final acceptance.

If a condition prevents useful continuation, create `.ai/pipeline/BLOCKED` with
a short reason. Otherwise do not create `BLOCKED`.

Your final response will be saved as `.ai/pipeline/reports/round-04.md`; make it
a concise completion report.
