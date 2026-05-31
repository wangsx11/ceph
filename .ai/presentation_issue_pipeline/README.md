# Presentation Issue Repair Pipeline

This pipeline is a fresh three-round Codex automation flow for the current
function and performance presentation issues.

## Goal

Repair and validate these user-reported issues:

1. Function `storage/FN-2`: the frontend evidence says the cold object waited
   `16.0s`, but the actual wait can be much shorter. The displayed wait must
   match the measured elapsed wait.
2. Function `storage/FN-4`: configurable compression and deduplication can fail
   on the second run because compression stats do not increase when the payload
   has already been deduplicated.
3. Performance `PF-2`: object-transfer latency should sample close to the
   100,000-object requirement, not around 1,790,000 samples.
4. Performance `PF-4`, `PF-5`, and `PF-6`: reduce slow startup-to-result time
   where practical while preserving the stated metric semantics.
5. Performance `PF-7`: presentation P999 should be below `900us` but not
   unrealistically low; the frontend result summary should show P999 only, not
   P50/P95/P99.

## Run

Use tmux so the three Codex sessions continue if SSH disconnects:

```bash
tmux new -s nr-presentation-issues 'bash .ai/presentation_issue_pipeline/run.sh; exec bash'
```

Reattach later:

```bash
tmux attach -t nr-presentation-issues
```

## Stop Or Resume

Stop before the next round:

```bash
touch .ai/presentation_issue_pipeline/STOP
```

Resume:

```bash
rm -f .ai/presentation_issue_pipeline/STOP
bash .ai/presentation_issue_pipeline/run.sh
```

Start from a specific round:

```bash
PIPELINE_START_ROUND=2 bash .ai/presentation_issue_pipeline/run.sh
```

Only run one round:

```bash
PIPELINE_END_ROUND=1 bash .ai/presentation_issue_pipeline/run.sh
```

## Rounds

- Round 1: fix the reported issues and run targeted validation.
- Round 2: try to reproduce the same issues; if any recur, fix them and
  validate again.
- Round 3: validation only. Do not modify source files. Run the full focused
  monitor pass and report `success` or `partial failure` with exact failed
  sections.

## Outputs

- `.ai/presentation_issue_pipeline/state.md`
- `.ai/presentation_issue_pipeline/reports/round-01.md`
- `.ai/presentation_issue_pipeline/reports/round-02.md`
- `.ai/presentation_issue_pipeline/reports/round-03.md`
- `.ai/presentation_issue_pipeline/logs/`
- `.ai/presentation_issue_pipeline/DONE` if Round 3 fully succeeds.
- `.ai/presentation_issue_pipeline/PARTIAL` if Round 3 completes but some
  section fails.
- `.ai/presentation_issue_pipeline/BLOCKED` if a round cannot continue safely.
- `.ai/presentation_issue_pipeline/FAILED` if Codex exec itself fails.

## Hardware Rule

Direct Codex sandbox runs may not expose RDMA devices. Hardware-dependent
checks should prefer host-side execution:

```bash
ssh xfusion3 'cd /home/wangshouxin/native-rdma-web && <command>'
```

Performance commands must use `timeout` and probe `ssh xfusion4 hostname`
around high-risk runs.

## Context Safety Rule

Do not let Codex read large `history/` or `logs/` trees. The round prompts and
runner explicitly forbid broad reads over `**/history/**` and `**/logs/**`.
Use current `raw.json`, `summary.md`, bounded source sections, and explicitly
named small evidence files only. Broad searches must exclude histories/logs:

```bash
rg --glob '!**/history/**' --glob '!**/logs/**' ...
```
