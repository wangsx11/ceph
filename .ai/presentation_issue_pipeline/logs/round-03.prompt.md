# Presentation Issue Repair Pipeline

You are running in a fresh non-interactive Codex exec session.

Repository root: /home/wangshouxin/native-rdma-web
Pipeline dir: /home/wangshouxin/native-rdma-web/.ai/presentation_issue_pipeline
Round: 3

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
- /home/wangshouxin/native-rdma-web/.ai/presentation_issue_pipeline/reports/round-01.md
- /home/wangshouxin/native-rdma-web/.ai/presentation_issue_pipeline/reports/round-02.md

Round-specific instructions:

# Round 3: Validation Only

You are Round 3 of the presentation issue pipeline. This is a fresh non-
interactive Codex exec session.

## Objective

Run the final focused validation only. Do not modify source files.

## Hard Constraint

- No code edits.
- No `apply_patch`.
- No source-file rewrites.
- You may only read files, run checks, update `.ai/presentation_issue_pipeline/state.md`,
  and write the final report/markers.

## Required Reading

Read:

- `.ai/presentation_issue_pipeline/plan.md`
- `.ai/presentation_issue_pipeline/state.md`
- `.ai/presentation_issue_pipeline/reports/round-01.md`
- `.ai/presentation_issue_pipeline/reports/round-02.md`
- `docs/功能要求.md`
- `docs/性能要求.md`
- `functions/common/checks.py`
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

## Context Safety

Do not read bulk history/log content. Avoid commands that dump
`**/history/**` or `**/logs/**` into context. If using `rg`, exclude them:

```bash
rg --glob '!**/history/**' --glob '!**/logs/**' ...
```

Use current source, current `raw.json`/`summary.md`, and explicitly named small
evidence files only.

## Validation Focus

1. Confirm `storage/FN-2` evidence shows the actual elapsed wait.
2. Confirm `storage/FN-4` stays stable across consecutive runs.
3. Confirm `PF-2` sample count is near the requirement, not massively above it.
4. Confirm `PF-4`, `PF-5`, and `PF-6` still pass after tuning.
5. Confirm `PF-7` presentation summary shows only P999 in the visible result
   summary and does not claim strict RAID5 confirmation.

## Result Rules

- If every focused section passes, create `.ai/presentation_issue_pipeline/DONE`.
- If one or more sections fail, create `.ai/presentation_issue_pipeline/PARTIAL`
  and list the failed sections explicitly.
- If the validation cannot continue safely, create
  `.ai/presentation_issue_pipeline/BLOCKED`.

## Required Output

Update `.ai/presentation_issue_pipeline/state.md` with:

- final validation commands;
- per-section pass/fail status;
- whether `DONE` or `PARTIAL` was created;
- residual risks if any.

Your final response will be saved as
`.ai/presentation_issue_pipeline/reports/round-03.md`.

End-of-round requirements:
- Update /home/wangshouxin/native-rdma-web/.ai/presentation_issue_pipeline/state.md.
- Mention changed files and validation commands in the final response.
- Keep the final response concise enough for the next round to read.
- If you cannot continue safely, write /home/wangshouxin/native-rdma-web/.ai/presentation_issue_pipeline/BLOCKED; otherwise leave it absent.
