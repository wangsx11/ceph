# Round 1: Full Diagnosis

You are Round 1 of the native_rdma acceptance pipeline. This is an independent
Codex exec session. Do not assume chat history.

## Objective

Diagnose the current repository state end to end. Prefer observation and
evidence over fixes in this round. Small non-invasive fixes are allowed only if
they unblock diagnosis and are clearly recorded.

## Required Reading

Read these first:

- `docs/project-onboarding-skill/SKILL.md`
- `.ai/pipeline/plan.md`
- `.ai/pipeline/state.md`
- `docs/功能要求.md`
- `docs/性能要求.md`
- `docs/演示要求.md`

Then inspect the relevant startup, dashboard, function, and performance entry
points before running them.

## Required Checks

Run or directly verify these paths:

- `cd native_rdma && bash start.sh`
- Function dashboard route and related APIs.
- Performance dashboard route and related APIs.
- Demo dashboard route and demo 3, 5, and 6 related APIs.
- `bash functions/run_all.sh`
- `bash performances/run_all.sh`

Use reasonable `timeout` wrappers for high-risk or potentially hanging commands.
When running high-load tests, record elapsed time and monitor SSH/network
stability. At minimum, record whether `ssh xfusion4 hostname` remains responsive
before and after risky tests. If practical, capture ping or repeated SSH probe
logs under `.ai/pipeline/logs/`.

## What To Identify

Record:

- commands that fail and their exit codes;
- commands that hang or exceed presentation-friendly time;
- commands that appear to destabilize networking or SSH;
- frontend buttons/routes/API calls that fail;
- test points that pass but do not cover the written requirement;
- scripts that are unsafe for a live demo;
- evidence files that are stale, missing, or misleading.

## Constraints

- Do not perform broad refactors in this round.
- Do not fabricate results.
- Do not mark an item covered without evidence.
- Do not revert unrelated user changes.

## Required Output

Update `.ai/pipeline/state.md` with:

- Round 1 status;
- confirmed failures;
- suspected failures;
- coverage gaps;
- long-running or network-risky commands;
- recommended priorities for Round 2.

If a condition prevents useful continuation, create `.ai/pipeline/BLOCKED` with
a short reason. Otherwise do not create `BLOCKED`.

Your final response will be saved as `.ai/pipeline/reports/round-01.md`; make it
a concise but complete diagnosis report.
