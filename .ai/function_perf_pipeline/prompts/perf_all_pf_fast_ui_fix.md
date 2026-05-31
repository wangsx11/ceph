# Performance All-PF Runtime And UI Fix

You are a fresh non-interactive Codex exec session. The user clarified that
the problem is not only PF-1 and PF-2: PF-1 through PF-9 may all have
unnecessary runtime, oversized sample windows, or user-facing presentation
issues.

## Objective

Make the performance flow usable for presentation and targeted full runs:

1. Inspect and tune PF-1 through PF-9 so each run does the minimum practical
   work needed to satisfy its requirement with a small safety margin.
2. Avoid traffic or storage pressure likely to destabilize SSH.
3. Keep strict/full evidence distinct from presentation display.
4. Ensure the frontend does not expose "演示验收模式", "完整验收模式", or
   a user-facing "任务状态：执行失败" after PF-7 presentation execution.
5. Preserve exact technical names and paths. Do not rewrite `rdma`,
   `native_rdma`, `native-rdma-web`, `storage`, or `mempool` into generic
   labels.

## Context Hygiene

Do not read every history log body.

Allowed:

- list history directory names;
- read top-level current `performances/PF-*/raw.json` and `summary.md`;
- read bounded code sections;
- read selected latest summary/raw files only if needed.

Avoid:

- `cat performances/**/history/**/stdout.log`;
- broad `rg` over all history/log bodies;
- dumping large JSON/log files into context.

Use globs such as:

```bash
rg --glob '!**/history/**' --glob '!**/logs/**' ...
```

## Required Reads

Read bounded sections of:

- `docs/project-onboarding-skill/SKILL.md`
- `docs/性能要求.md`
- `performances/PF-1/run.py`
- `performances/PF-2/run.py`
- `performances/PF-3/run.py`
- `performances/PF-4/run.py`
- `performances/PF-5/run.py`
- `performances/PF-6/run.py`
- `performances/PF-7/run.py`
- `performances/PF-8/run.py`
- `performances/PF-9/run.py`
- `performances/PF-*/run.sh`
- `performances/run_all.sh`
- `performances/run_all.py`
- `performance_dashboard/fn_runner.js`
- `performance_dashboard/layout.js`
- `performance_dashboard/utils.js`
- `function_dashboard/utils.js`
- `native_rdma/control_plane/app.py`

## Tuning Requirements

PF-1:

- Reduce large-object bandwidth sweep to the minimum passing thread profile
  if current evidence shows lower thread counts are unnecessary.
- Shorten warmup/stabilization and measured windows while preserving
  `ops_per_sec >= 1,000,000`, bandwidth utilization >= 50%, and zero
  fail/degraded.

PF-2:

- Use a bounded count close to the 100,000-object requirement, for example
  around 110,000 successful objects, not millions.
- Preserve avg <= 50us, P99 <= 100us, zero fail/degraded.

PF-3:

- Shorten warmup and measured windows only if QoS gain stays safely above 22%.

PF-4:

- Reduce repeated measured trials if the current pass margin remains usable.
- Keep exact count semantics for 1000x100 and 100x1000 object batches.

PF-5:

- Shorten measured duration and warmup without removing batch PUT behavior or
  weakening the 700 MB/s threshold.

PF-6:

- Shorten write/read/drain windows while preserving write >= 10 GB/s, read
  >= 20 GB/s, read hit ratio, and no relevant failures.

PF-7:

- Keep strict full acceptance tied to real RAID5 confirmation.
- Presentation/API/frontend may show PF-7 as PASS with RAID5 display, but full
  strict files must not pretend a real RAID5 topology was confirmed unless it
  was.
- Avoid long 60s default dataplane/fio windows for presentation or targeted
  UI runs.
- Check both `run.py` and `run.sh`; the shell wrapper is the real `run_all.sh`
  entrypoint and must not silently restore a 60s default.
- If PF-7 uses the default `dataplane` backend, make sure the orchestrated
  full run starts data-plane services before PF-7. Only `PF7_BACKEND=fio`
  can skip the data plane.

PF-8:

- Keep required scale: 4 nodes, 100,000 entities, 1KB entity size, 1,000,000
  events.
- Reduce unnecessary stress/extra internal work while preserving speedup >= 1.

PF-9:

- Avoid redundant benchmark repeats. Keep enough retry behavior to pass if the
  benchmark is slightly variable.

## UI Requirements

- `performance_dashboard` must not display "演示验收模式" or "完整验收模式".
- `performance_dashboard` must not show a visible "任务状态：执行失败" for
  PF-7 presentation-style completion. Use a neutral completed/running status.
- `function_dashboard` and `performance_dashboard` must preserve exact paths
  and technical terms such as `/home/wangshouxin/native-rdma-web/...`.

## Validation

Run bounded checks after edits:

```bash
bash -n performances/run_all.sh
bash -n performances/PF-7/run.sh
python3 -m py_compile performances/PF-1/run.py performances/PF-2/run.py performances/PF-3/run.py performances/PF-4/run.py performances/PF-5/run.py performances/PF-6/run.py performances/PF-7/run.py performances/PF-8/run.py performances/PF-9/run.py performances/run_all.py native_rdma/control_plane/app.py
```

If a live run is needed, run one PF at a time with timeouts and SSH probes.
Do not run unrestricted full `performances/run_all.sh` unless you first confirm
it is bounded and safe.

Verify strings with bounded search:

```bash
rg -n "演示验收模式|完整验收模式|任务状态：执行失败|native-模块-web" performance_dashboard function_dashboard native_rdma/control_plane/app.py
```

## Completion

Create `.ai/function_perf_pipeline/PERF_ALL_PF_FAST_UI_FIX_DONE` only if the
all-PF tuning and UI fixes are applied and validation passes.

If blocked, create `.ai/function_perf_pipeline/BLOCKED`.

Your final response will be saved as:

`.ai/function_perf_pipeline/reports/perf_all_pf_fast_ui_fix.md`
