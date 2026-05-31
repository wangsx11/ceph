# Performance Tuning And UI Fix

You are running a fresh Codex exec session to address several small but visible
issues:

1. PF-1 to PF-9 still have runtime or sizing issues in the full performance
   flow.
2. PF-2 currently produces far more than the requirement and should be tuned
   to stay close to the requirement while still passing.
3. PF-1, PF-3, PF-4, PF-5, PF-6, PF-7, PF-8, and PF-9 should all be checked
   for unnecessary duration, retry, warmup, or sweep overhead.
4. PF-7 in the UI sometimes shows "任务状态：执行失败" and that should not be
   shown in the user-facing presentation flow.
5. The performance frontend no longer needs the visible "演示验收模式" label.
6. The function/frontend text sanitizer is mangling valid text like
   "native-rdma-web" by replacing "rdma" with "模块". That must be fixed.
7. The acceptance conclusion text that mentions
   "数据面日志包含 IoScheduler ... /home/wangshouxin/native-模块-web/..." is
   wrong and should keep the real repo name instead of rewriting it.

## Output Limits

Do not scan history log bodies.
You may inspect filenames, summary files, and bounded code sections.

If using `rg`, exclude histories and logs:

```bash
rg --glob '!**/history/**' --glob '!**/logs/**' --glob '!*.json' ...
```

## Required Reads

Read bounded sections of:

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
- `performances/run_all.py`
- `performance_dashboard/fn_runner.js`
- `performance_dashboard/layout.js`
- `performance_dashboard/utils.js`
- `function_dashboard/utils.js`
- `native_rdma/control_plane/app.py`
- `functions/common/checks.py`

## Performance Tuning Goals

### PF-2

Tune PF-2 so it satisfies the written requirement with a small margin, not an
order of magnitude overrun. Current complaint:

- measured samples are around 1,949,735/100,000.

Reduce the duration / max-iops / thread / batch configuration if needed, while
still preserving:

- `ops_ok >= 100000`
- `avg <= 50us`
- `p99 <= 100us`
- zero fail/degraded

### PF-1

Reduce the total runtime where possible while preserving PASS. Prefer tighter
measured windows, fewer unnecessary sweeps, and smaller warmup/guard values if
the existing logic allows it without harming the threshold.

### PF-3 to PF-9

Inspect each PF for avoidable overhead and tighten them where safe:

- PF-3: reduce the measured window only as far as the gain remains stable.
- PF-4: reduce repeated measured trials if the pass/fail margin stays intact.
- PF-5: shorten warmup and measured duration without cutting batch behavior.
- PF-6: trim write/read/drain windows while keeping bandwidth thresholds.
- PF-7: keep strict/full acceptance separate from presentation PASS; check
  both `run.py` and `run.sh` so the actual `run_all.sh` entrypoint does not
  keep an old 60s default.
- PF-8: keep the required problem size but reduce any unnecessary stress.
- PF-9: keep the benchmark representative while avoiding redundant repeats.

### PF-7 UI

In the performance dashboard, stop showing a user-facing "任务状态：执行失败"
for the presentation flow. The visible summary should be a clean PASS in the
presentation UI.

Also remove the visible "演示验收模式" label from the performance frontend.

### Sanitizer

Fix the sanitizer so it does not rewrite legitimate repo names or technical
terms. Keep it from turning:

- `native-rdma-web` into `native-模块-web`
- `rdma` into `模块`

The user-facing text should preserve exact technical paths and names.

## Validation

Run bounded checks after edits:

```bash
bash -n performances/run_all.sh
bash -n performances/PF-7/run.sh
python3 -m py_compile performances/PF-1/run.py performances/PF-2/run.py performances/PF-7/run.py performances/run_all.py native_rdma/control_plane/app.py
```

If it is safe to run targeted performance checks, prefer small bounded runs or
existing history selection logic rather than full unrestricted suites.

Verify the UI strings via the code and, if possible, a quick API response:

```bash
curl -s http://127.0.0.1:5000/api/performance/presentation_summary
```

## Completion

Create `.ai/function_perf_pipeline/PERF_TUNING_UI_FIX_DONE` only if the tuning
and UI fixes are applied and validated.

If blocked, create `.ai/function_perf_pipeline/BLOCKED`.

Your final response will be saved as:

`.ai/function_perf_pipeline/reports/perf_tuning_and_ui_fix.md`
