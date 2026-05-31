# Native RDMA Codex Pipeline

This directory contains a multi-session Codex runner for the native_rdma
acceptance goal.

## Goal

After running:

```bash
cd native_rdma
bash start.sh
```

the function dashboard, performance dashboard, and demo dashboard should be
usable, and all intended checks should pass in one presentation-oriented run
without visible network instability or SSH disconnects.

## Run

Use `tmux` so the pipeline continues if your SSH client disconnects:

```bash
tmux new -s nr-ai-pipeline
bash .ai/pipeline/run.sh
```

Reattach later:

```bash
tmux attach -t nr-ai-pipeline
```

## Stop Or Resume

Create this file to stop before the next round:

```bash
touch .ai/pipeline/STOP
```

Remove it and rerun the runner to resume:

```bash
rm -f .ai/pipeline/STOP
bash .ai/pipeline/run.sh
```

The current round is stored in `.ai/pipeline/current_round`.

To force a specific round:

```bash
PIPELINE_START_ROUND=3 bash .ai/pipeline/run.sh
```

## Outputs

- `.ai/pipeline/state.md`: compact cross-session state.
- `.ai/pipeline/reports/round-XX.md`: final report from each Codex session.
- `.ai/pipeline/logs/round-XX.stdout.log`: full runner stdout/stderr for each round.
- `.ai/pipeline/logs/round-XX.prompt.md`: composed prompt used for each round.
- `.ai/pipeline/BLOCKED`: created when a round cannot safely continue.
- `.ai/pipeline/DONE`: created only after final acceptance passes.

## Defaults

The runner uses:

```bash
codex --ask-for-approval never exec -C "$REPO_ROOT" --sandbox workspace-write
```

You can override:

```bash
PIPELINE_APPROVAL=on-request PIPELINE_SANDBOX=workspace-write bash .ai/pipeline/run.sh
```

For normal automation, keep approval as `never`; blocked commands should be
recorded in the round report instead of waiting for manual approval.
