# Presentation Issue Repair Pipeline

You are running in a fresh non-interactive Codex exec session.

Repository root: /home/wangshouxin/native-rdma-web
Pipeline dir: /home/wangshouxin/native-rdma-web/.ai/presentation_issue_pipeline
Round: 2

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

Round-specific instructions:

# Round 2: Reproduce And Recheck

You are Round 2 of the presentation issue pipeline. This is a fresh non-
interactive Codex exec session.

## Objective

Try to reproduce the same issues after Round 1 fixes. If any issue recurs,
repair it and validate again.

## Required Reading

Read:

- `.ai/presentation_issue_pipeline/plan.md`
- `.ai/presentation_issue_pipeline/state.md`
- `.ai/presentation_issue_pipeline/reports/round-01.md`
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

## Work Scope

1. Re-run `storage/FN-2` and confirm the displayed wait matches the measured
   elapsed wait, not the configured maximum wait window.
2. Re-run `storage/FN-4` at least twice and confirm the second run no longer
   fails because compression stats remain flat while dedup stats increase.
3. Re-run `PF-2` and confirm the measured samples are near the requirement,
   not far above it.
4. Re-run `PF-4`, `PF-5`, and `PF-6` with bounded commands and confirm the
   runtime trims still preserve the metrics.
5. Re-check `PF-7` presentation output and summary to confirm only P999 is
   shown in the visible result summary, while strict RAID5 confirmation stays
   separate.

## Validation

- Use timeouts.
- Probe `ssh xfusion4 hostname` before and after high-risk performance checks.
- Run one PF at a time when diagnosing.

## Required Output

Update `.ai/presentation_issue_pipeline/state.md` with:

- what was reproduced or not reproduced;
- what additional fixes were needed;
- the remaining issues, if any, for Round 3 validation.

If safe continuation is impossible, create `.ai/presentation_issue_pipeline/BLOCKED`.

Your final response will be saved as
`.ai/presentation_issue_pipeline/reports/round-02.md`.

End-of-round requirements:
- Update /home/wangshouxin/native-rdma-web/.ai/presentation_issue_pipeline/state.md.
- Mention changed files and validation commands in the final response.
- Keep the final response concise enough for the next round to read.
- If you cannot continue safely, write /home/wangshouxin/native-rdma-web/.ai/presentation_issue_pipeline/BLOCKED; otherwise leave it absent.
