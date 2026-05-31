# Function And Performance Focused Codex Pipeline

This pipeline is a fresh follow-up flow for the latest known issues:

- performance runs can still destabilize SSH;
- some performance panels still do not pass;
- function checks must run twice consecutively without regressions;
- RDMA FN-4, CPU/GPU high-speed direct access, must be rechecked because it
  previously worked but latest evidence may show a waiver/failure.

This pipeline intentionally does not reuse `.ai/pipeline/DONE`. The previous
pipeline is historical evidence only.

## Run

Use a separate tmux session:

```bash
tmux new -s nr-function-perf 'bash .ai/function_perf_pipeline/run.sh; exec bash'
```

Reattach:

```bash
tmux attach -t nr-function-perf
```

Stop before the next round:

```bash
touch .ai/function_perf_pipeline/STOP
```

Resume:

```bash
rm -f .ai/function_perf_pipeline/STOP
bash .ai/function_perf_pipeline/run.sh
```

## Outputs

- `.ai/function_perf_pipeline/state.md`
- `.ai/function_perf_pipeline/reports/round-XX.md`
- `.ai/function_perf_pipeline/logs/round-XX.stdout.log`
- `.ai/function_perf_pipeline/logs/round-XX.prompt.md`
- `.ai/function_perf_pipeline/BLOCKED`
- `.ai/function_perf_pipeline/DONE`

## Default Codex Command

```bash
codex --ask-for-approval never exec -C "$REPO_ROOT" --sandbox workspace-write
```

Hardware-dependent commands should prefer host-side execution through
`ssh xfusion3` when direct sandbox execution cannot see RDMA/GPU devices.
