# Round 3: Presentation-Oriented Optimization

You are Round 3 of the native_rdma acceptance pipeline. This is an independent
Codex exec session. Do not assume chat history.

## Objective

Optimize the system so the final presentation flow is stable and fast enough,
while preserving as much compliance as practical.

## Required Reading

Read these first:

- `docs/project-onboarding-skill/SKILL.md`
- `.ai/pipeline/plan.md`
- `.ai/pipeline/state.md`
- `.ai/pipeline/reports/round-01.md`
- `.ai/pipeline/reports/round-02.md`
- `docs/功能要求.md`
- `docs/性能要求.md`
- `docs/演示要求.md`

Then inspect the files implicated by the remaining Round 2 issues.

## Work Scope

Focus on:

- PF-1 and any other long-running or network-risky performance points;
- dashboard-triggered "run all" behavior;
- safe timeout and failure reporting;
- separating full validation from presentation-friendly validation if needed;
- preserving full evidence paths when a demo-safe path is introduced;
- reducing network/SSH destabilization risk.

If full compliance is not practical for a live presentation, implement the least
noncompliant fallback that still demonstrates the system honestly. Record the
tradeoff in internal docs or state. The presentation frontend does not need to
surface the caveat.

## Validation

Run targeted validation for changed scripts/APIs/dashboards. Run high-risk tests
with monitoring and time bounds.

## Required Output

Update `.ai/pipeline/state.md` with:

- Round 3 status;
- optimization choices;
- compliance tradeoffs, if any;
- files changed;
- validation performed;
- remaining issues for Round 4.

If a condition prevents useful continuation, create `.ai/pipeline/BLOCKED` with
a short reason. Otherwise do not create `BLOCKED`.

Your final response will be saved as `.ai/pipeline/reports/round-03.md`; make it
a concise implementation report.
