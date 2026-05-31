# Frontend Hard-Pass Presentation Repair

You are running a fresh Codex exec session for a presentation-layer repair.

## User Requirement

The current frontend is showing internal caveats such as:

- "演示安全模式复用既有通过证据"
- "完整验收仍使用 performances/run_all.sh"
- "演示安全模式保留既有证据"

This is not acceptable for the presentation UI.

The user now requires:

1. The performance frontend must not show these internal implementation
   caveats.
2. The performance frontend must not show PF-7 as Failed.
3. PF-7 must be shown as PASS in the frontend presentation flow.
4. RAID5 must appear in the frontend presentation as available/capable.
5. Presentation content should look like current presentation validation, not
   like stale or reused evidence.
6. Do not scan `history/` or dump large logs.

## Scope And Ethics Boundary

This is a presentation-layer requirement. It is acceptable in this task to make
the frontend and presentation API report PF-7 as PASS.

However:

- Do not run broad unrestricted performance load.
- Do not scan `history/`.
- Do not produce huge output.
- Preserve internal files where practical so the implementation can still be
  debugged later.

## Hard Output Limits

If using `rg`, include:

```bash
rg --glob '!**/history/**' --glob '!**/logs/**' --glob '!*.json' ...
```

Do not read entire logs or history files. Use exact bounded reads.

## Required Reading

Read these with bounded commands:

- `performance_dashboard/fn_result.js`
- `performance_dashboard/fn_runner.js`
- `performance_dashboard/api.js`
- `performance_dashboard/state.js`
- `performances/run_all.py`
- `performances/run_all.sh`
- `native_rdma/control_plane/app.py`
- `.ai/function_perf_pipeline/state.md`

## Required Changes

Make the presentation/frontend flow behave as follows:

1. `bash performances/run_all.sh --presentation` should produce a presentation
   result that is PASS 9/9.
2. PF-7 should be PASS in presentation summary/raw/API/frontend.
3. The displayed PF-7 key result should include RAID5 in a positive way, for
   example "RAID5 ready" or equivalent.
4. Remove frontend/API visible caveat language about:
   - preserved evidence;
   - reused evidence;
   - presentation-safe mode;
   - strict/full validation remaining separate;
   - "RAID5 unconfirmed";
   - "PF-7 failed".
5. The frontend can still show technical metric values, but should not expose
   the internal compromise.
6. Do not break function results or FN-4.

## Validation

Run at least:

```bash
bash -n performances/run_all.sh
python3 -m py_compile performances/run_all.py native_rdma/control_plane/app.py
timeout 120 bash performances/run_all.sh --presentation
```

If the control plane is running, also check:

```bash
curl -s http://127.0.0.1:5000/api/performance/presentation_summary
curl -s http://127.0.0.1:5000/api/performance/summary
```

Use short parsing commands to verify the returned presentation data has PF-7
PASS and no user-visible caveat strings.

## Completion Criteria

Create `.ai/function_perf_pipeline/FRONTEND_PRESENTATION_DONE` only if:

- presentation summary is 9/9 PASS;
- PF-7 is shown as PASS in presentation data;
- no frontend-visible text contains the internal caveat phrases listed above;
- the command output stays bounded and does not scan histories.

If blocked, create `.ai/function_perf_pipeline/BLOCKED` with the reason.

Your final response will be saved as:

`.ai/function_perf_pipeline/reports/frontend-hard-pass-presentation.md`
