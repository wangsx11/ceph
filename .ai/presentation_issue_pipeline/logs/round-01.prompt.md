# Presentation Issue Repair Pipeline

You are running in a fresh non-interactive Codex exec session.

Repository root: /home/wangshouxin/native-rdma-web
Pipeline dir: /home/wangshouxin/native-rdma-web/.ai/presentation_issue_pipeline
Round: 1

Important:
- Do not assume prior chat history.
- Preserve unrelated user changes in the dirty working tree.
- Read the local files listed below.
- Do not read large history/log folders. Never run broad cat/sed/rg over
  **/history/** or **/logs/** bodies. Use current raw/summary files and
  explicitly named small files only.
- When searching, exclude histories/logs unless the round prompt names a
  specific small file:
  rg --glob '!**/history/**' --glob '!**/logs/**' ...
- Round 3 is validation-only and must not edit source files.
- If blocked, create /home/wangshouxin/native-rdma-web/.ai/presentation_issue_pipeline/BLOCKED with a short reason.
- If all focused checks pass in Round 3, create /home/wangshouxin/native-rdma-web/.ai/presentation_issue_pipeline/DONE; if some
  sections still fail, create /home/wangshouxin/native-rdma-web/.ai/presentation_issue_pipeline/PARTIAL and describe the failed sections.

Required pipeline files:
- /home/wangshouxin/native-rdma-web/.ai/presentation_issue_pipeline/plan.md
- /home/wangshouxin/native-rdma-web/.ai/presentation_issue_pipeline/state.md

Previous reports, if present:

Round-specific instructions:

# Round 1: Repair Current Issues

You are Round 1 of the presentation issue pipeline. This is a fresh non-
interactive Codex exec session.

## Objective

Fix the reported function and performance issues in the source code and update
the relevant summaries/front-end bindings.

## Required Reading

Read:

- `.ai/presentation_issue_pipeline/plan.md`
- `.ai/presentation_issue_pipeline/state.md`
- `docs/project-onboarding-skill/SKILL.md`
- `docs/功能要求.md`
- `docs/性能要求.md`
- `docs/function_dashboard验证与实现文案.md`
- `docs/performance_dashboard验证与实现文案.md`
- `functions/common/checks.py`
- `function_dashboard/fn_runner.js`
- `performance_dashboard/fn_runner.js`
- `performance_dashboard/fn_result.js`
- `performance_dashboard/layout.js`
- `performance_dashboard/api.js`
- `native_rdma/control_plane/app.py`
- `performances/PF-2/run.py`
- `performances/PF-4/run.py`
- `performances/PF-5/run.py`
- `performances/PF-6/run.py`
- `performances/PF-7/run.py`
- `performances/run_all.py`
- `performances/run_all.sh`

## Context Safety

Do not read bulk history/log content. Avoid commands that dump
`**/history/**` or `**/logs/**` into context. If using `rg`, exclude them:

```bash
rg --glob '!**/history/**' --glob '!**/logs/**' ...
```

Use current source, current `raw.json`/`summary.md`, and explicitly named small
evidence files only.

## Work Scope

Implement the following repairs:

1. `storage/FN-2`: replace the displayed `16.0s` wait text with the actual
   elapsed wait that was observed before the cold object hit `nvme_promote`.
2. `storage/FN-4`: make the second targeted run robust by ensuring the
   compression and dedup validation can both increase on repeated runs without
   false failure from duplicate-only payload selection.
3. `PF-2`: tune the default sample size and/or wrapper so the measured count is
   close to the 100,000-object requirement rather than ~1.79M.
4. `PF-4`, `PF-5`, and `PF-6`: remove avoidable runtime overhead while
   preserving the written thresholds and the intended batch/throughput
   semantics.
5. `PF-7`: ensure the presentation path shows only P999 in the result summary,
   keeps a credible P999 below 900us, and keeps strict RAID5 confirmation
   separate from presentation display.

## Validation

Use bounded validation only. Prefer one PF at a time. Use host-side commands
for hardware-sensitive checks when needed.

Helpful examples:

```bash
ssh xfusion3 'cd /home/wangshouxin/native-rdma-web && bash functions/storage/FN-2/run.sh'
ssh xfusion3 'cd /home/wangshouxin/native-rdma-web && bash functions/storage/FN-4/run.sh'
ssh xfusion3 'cd /home/wangshouxin/native-rdma-web && bash performances/PF-2/run.sh'
```

Keep `ssh xfusion4 hostname` probes around higher-risk performance runs.

## Required Output

Update `.ai/presentation_issue_pipeline/state.md` with:

- what was fixed in Round 1;
- which validation commands were run;
- any remaining issues to re-check in Round 2.

If safe continuation is impossible, create `.ai/presentation_issue_pipeline/BLOCKED`.

Your final response will be saved as
`.ai/presentation_issue_pipeline/reports/round-01.md`.

End-of-round requirements:
- Update /home/wangshouxin/native-rdma-web/.ai/presentation_issue_pipeline/state.md.
- Mention changed files and validation commands in the final response.
- Keep the final response concise enough for the next round to read.
- If you cannot continue safely, write /home/wangshouxin/native-rdma-web/.ai/presentation_issue_pipeline/BLOCKED; otherwise leave it absent.
