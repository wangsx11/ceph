# Frontend Latest Result Binding Repair

You are running a fresh Codex exec session to repair the performance dashboard
result binding after clicking "立即执行" / single-item run.

## User Symptom

After clicking the performance frontend run button and waiting for completion,
the page does not show the newest result. It appears to show older presentation
or baseline data instead. The user suspects the generated log/history naming may
not be collected.

## Constraints

- You may list history directory names and mtimes.
- Do not read the content of every history log.
- Do not recursively scan `history/` contents.
- Do not dump large logs or raw JSON.
- If using `rg`, include:

```bash
rg --glob '!**/history/**' --glob '!**/logs/**' --glob '!*.json' ...
```

## Required Reading

Read bounded sections of these files:

- `performance_dashboard/fn_runner.js`
- `performance_dashboard/layout.js`
- `performance_dashboard/api.js`
- `performance_dashboard/state.js`
- `native_rdma/control_plane/app.py`
- `performances/run_all.py`
- `performances/run_all.sh`

You may list recent history directories with commands like:

```bash
find performances/PF-7/history -maxdepth 1 -mindepth 1 -type d -printf '%T@ %f\n' | sort -nr | head
find performances/history -maxdepth 1 -mindepth 1 -type d -printf '%T@ %f\n' | sort -nr | head
```

Do not open each history directory's logs.

## Likely Root Cause To Verify

The frontend defaults to `profile="presentation"`.

After a single-item run:

- `/api/performance/run_one` creates `performances/PF-N/history/web_<timestamp>_<job_id>/`.
- the polling code calls `refreshSummary(false)` and `loadCurrentFunction()`;
- because the active profile is still `presentation`, it calls
  `/api/performance/fn/...?...profile=presentation`;
- the presentation result selector may prefer baseline/presentation data over
  the just-created `web_...` run, so the UI looks stale.

Confirm this from code and fix it.

## Required Fix

After any frontend-triggered performance job finishes, the dashboard should show
the newest job result for the current PF.

Acceptable implementation options:

1. Add support for a `job_id` or `history_dir` query to
   `/api/performance/fn/<module>/<pf_id>` and make the frontend request that
   exact history after a job finishes.
2. Or change presentation result selection so the newest `web_...` history for
   the selected PF is preferred over baseline/preserved data, while still
   annotating PF-7 as presentation PASS.
3. Or store the last completed job in frontend state and load that exact result.

The fix must handle both:

- single PF run (`run_one`);
- presentation run-all (`run_all` profile presentation).

## Presentation Requirements

- PF-7 must display PASS in frontend presentation.
- RAID5 must display positively in presentation.
- Do not show "Failed" for PF-7 in presentation.
- Do not show internal caveats like preserved evidence, reused evidence,
  strict/full separation, or "RAID5 unconfirmed".

## Validation

Run syntax/compile checks:

```bash
python3 -m py_compile native_rdma/control_plane/app.py performances/run_all.py
bash -n performances/run_all.sh
```

Run or simulate bounded API checks. If the Flask control plane is running, use
real API checks:

```bash
curl -s http://127.0.0.1:5000/api/performance/presentation_summary
curl -s 'http://127.0.0.1:5000/api/performance/fn/performance/PF-7?profile=presentation'
```

If you need a fresh run to test binding, prefer a low-risk PF or use existing
latest history directory name. Avoid full high-load all-PF runs.

Verify:

- newest web history can be selected and displayed;
- after a job id/history dir is known, the frontend loads that exact result;
- PF-7 presentation result is PASS;
- no user-facing caveat strings remain in presentation results.

## Completion

Create `.ai/function_perf_pipeline/LATEST_RESULT_BINDING_DONE` only if the
binding issue is fixed and validation passes.

If blocked, create `.ai/function_perf_pipeline/BLOCKED` with the exact reason.

Your final response will be saved as:

`.ai/function_perf_pipeline/reports/frontend-latest-result-binding.md`
