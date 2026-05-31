# Final Focused Repair: FN-3 Peer Readback, RAID5 Presentation, No History Scan

You are running a fresh Codex exec session for the final focused repair after
the previous Round 4 failed.

## Why The Previous Round Failed

Round 4 found a real function regression first:

- `functions/rdma/FN-3/logs/run_20260527_130549.log`
- `RPC_KV_PUT_HI` succeeded.
- `RPC_KV_PUT_LO` succeeded.
- Low-priority peer readback succeeded.
- High-priority peer readback failed with `not found`.

Then the session ran a broad `rg` that scanned large `history/` trees, expanded
the context to about 225k tokens, and the provider returned HTTP 400. Do not
repeat that.

## Hard Output Limits

Do not run broad repository searches that include histories or logs.

If you use `rg`, include these filters:

```bash
rg --glob '!**/history/**' --glob '!**/logs/**' --glob '!*.json' --glob '!*.raw' ...
```

Do not run `cat` on large logs, JSON files, or history outputs.

For logs, inspect exact files with bounded commands only, for example:

```bash
sed -n '1,140p' functions/rdma/FN-3/logs/run_20260527_130549.log
tail -n 120 .ai/function_perf_pipeline/logs/round-04.stdout.log
```

If a command may output more than 250 lines, redirect it to a file and summarize
with `head`, `tail`, or a targeted parser.

## Required Reading

Read these exact files first:

- `.ai/function_perf_pipeline/state.md`
- `.ai/function_perf_pipeline/reports/round-03.md`
- `functions/rdma/FN-3/logs/run_20260527_130549.log`
- `functions/rdma/FN-3/logs/run_20260527_130549.json`
- `functions/common/checks.py`
- `native_rdma/data_plane/main.cpp`
- `native_rdma/data_plane/qos/qos_sched.cpp`
- `native_rdma/data_plane/replication/replicator.cpp`
- `native_rdma/data_plane/router/object_router.cpp`
- `performance_dashboard/`
- `native_rdma/control_plane/app.py`

Use exact, bounded reads.

## Task 1: Explain And Fix FN-3 Peer Readback

Diagnose why `rdma/FN-3` can write the high-priority object successfully but
peer readback returns `not found`.

Likely areas to inspect:

- high-priority QP / QoS path replication behavior;
- peer index visibility after RDMA write;
- route metadata propagation;
- immediate readback race after PUT;
- differences between `RPC_KV_PUT_HI` and `RPC_KV_PUT_LO`;
- test logic in `functions/common/checks.py::rdma_fn3`.

Do not solve this by skipping peer readback. The function point must still prove
that both high and low priority paths write over RDMA and become visible on the
peer.

Acceptable fixes include:

- fixing actual data-plane peer metadata/index propagation;
- fixing high-priority replication path behavior;
- adding a bounded peer-readback wait/retry when the data plane is legitimately
  asynchronous at the metadata visibility layer.

## Task 2: Function Consecutive Pass

After the fix, run the function suite twice consecutively host-side with SSH
probes:

```bash
ssh xfusion4 hostname
ssh xfusion3 'cd /home/wangshouxin/native-rdma-web && bash functions/run_all.sh'
ssh xfusion3 'cd /home/wangshouxin/native-rdma-web && bash functions/run_all.sh'
ssh xfusion4 hostname
```

Use `timeout` wrappers. If this is unsafe, explain why and create
`.ai/function_perf_pipeline/BLOCKED`.

## Task 3: RAID5 Presentation Handling

The user asked to ignore strict RAID5 for now but make the frontend presentation
reflect RAID5.

Do not falsify strict backend evidence:

- Do not set `raid5_confirmed=true` unless a real RAID5 topology is proven.
- Do not change strict full raw results to claim PF-7 strict pass without proof.

What you may do:

- Make the frontend/presentation summary show a RAID5 capability/presentation
  badge or text based on presentation evidence.
- Keep strict/full status internally distinct.
- Ensure the presentation path can show a clean pass while strict PF-7 evidence
  remains documented as not currently confirmed.

## Task 4: Performance Presentation Pass Without SSH Instability

Verify the presentation-safe performance path:

```bash
ssh xfusion4 hostname
ssh xfusion3 'cd /home/wangshouxin/native-rdma-web && timeout 120 bash performances/run_all.sh --presentation'
ssh xfusion4 hostname
```

Also verify the relevant frontend/API summaries after the run. Do not run the
unrestricted full all-PF suite unless you add timeouts and SSH probes.

## Completion Criteria

Create `.ai/function_perf_pipeline/DONE` only if:

- FN-3 is fixed and function suite passes twice consecutively;
- FN-4 remains pass or is not regressed;
- performance presentation path passes and does not break SSH probes;
- frontend/presentation content shows RAID5 capability/presentation evidence
  without falsifying strict full raw results;
- `.ai/function_perf_pipeline/state.md` is updated with exact commands,
  results, files changed, and residual risks.

If any criterion cannot be met, create `.ai/function_perf_pipeline/BLOCKED`
with the exact reason.

Your final response will be saved as
`.ai/function_perf_pipeline/reports/final-repair-no-history.md`.
