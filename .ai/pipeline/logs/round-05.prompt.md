# Automated Native RDMA Pipeline

You are running in a fresh non-interactive Codex exec session.

Repository root: /home/wangshouxin/native-rdma-web
Pipeline dir: /home/wangshouxin/native-rdma-web/.ai/pipeline
Round: 5

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
- /home/wangshouxin/native-rdma-web/.ai/pipeline/reports/round-02.md
- /home/wangshouxin/native-rdma-web/.ai/pipeline/reports/round-03.md
- /home/wangshouxin/native-rdma-web/.ai/pipeline/reports/round-04.md

Round-specific instructions:

# Round 5: Final Acceptance

You are Round 5 of the native_rdma acceptance pipeline. This is an independent
Codex exec session. Do not assume chat history.

## Objective

Perform the final acceptance run. Create `.ai/pipeline/DONE` only if the final
target is satisfied.

## Required Reading

Read these first:

- `docs/project-onboarding-skill/SKILL.md`
- `.ai/pipeline/plan.md`
- `.ai/pipeline/state.md`
- `.ai/pipeline/reports/round-01.md`
- `.ai/pipeline/reports/round-02.md`
- `.ai/pipeline/reports/round-03.md`
- `.ai/pipeline/reports/round-04.md`
- `docs/功能要求.md`
- `docs/性能要求.md`
- `docs/演示要求.md`

## Required Final Checks

From a clean practical state:

1. Run or verify stop/cleanup as appropriate.
2. Run `cd native_rdma && bash start.sh`.
3. Verify function dashboard route and run the function checks.
4. Verify performance dashboard route and run the performance checks intended
   for the presentation flow.
5. Verify demo dashboard route and demo 3, 5, and 6 behavior.
6. Monitor network/SSH stability around high-risk checks.
7. Confirm result files and summaries match the actual run.

Use timeouts where needed to avoid indefinite hangs, but do not hide failures.

## Pass Criteria

Create `.ai/pipeline/DONE` only if:

- startup succeeds;
- function, performance, and demo frontends are reachable;
- intended function/performance/demo checks pass;
- known high-risk tests no longer destabilize SSH/networking in the checked
  flow;
- any unavoidable compliance tradeoffs are documented internally.

If any pass criterion is not met, do not create `DONE`. Instead create
`.ai/pipeline/BLOCKED` with the reason and update state with the remaining work.

## Required Output

Update `.ai/pipeline/state.md` with final acceptance status, commands run,
results, and residual risk.

Your final response will be saved as `.ai/pipeline/reports/round-05.md`; make it
a final acceptance report.

End-of-round requirements:
- Update /home/wangshouxin/native-rdma-web/.ai/pipeline/state.md.
- Mention changed files and validation commands in the final response.
- Keep the final response concise enough for the next round to read.
- If you cannot continue safely, write /home/wangshouxin/native-rdma-web/.ai/pipeline/BLOCKED; otherwise leave it absent.
