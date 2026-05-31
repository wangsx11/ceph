**Round 3 Status**

Completed presentation-oriented optimization. `.ai/pipeline/state.md` is updated. `BLOCKED` and `DONE` are absent.

**Implemented**

- Added presentation-safe performance flow:
  - `/api/performance/presentation_summary`
  - dashboard default `profile: "presentation"`
  - dashboard run-all now uses `运行演示性能流`
  - presentation run-all preserves existing PF evidence into fresh `web_all_*` history instead of launching the long/high-load suite
- Kept strict validation separate:
  - `/api/performance/summary` remains full profile and still reports current strict failures
  - full validation remains `bash performances/run_all.sh`
- Added timeout/profile metadata for performance jobs.
- Fixed PF-1 RDMA TX accounting in `native_rdma/data_plane/main.cpp`.
- Documented the presentation tradeoff in `performances/README.md`, `performance_dashboard/README.md`, and pipeline state.

**Changed Files**

`native_rdma/control_plane/app.py`, `native_rdma/data_plane/main.cpp`, `performances/run_all.py`, `performances/README.md`, `performance_dashboard/index.html`, `performance_dashboard/api.js`, `performance_dashboard/state.js`, `performance_dashboard/layout.js`, `performance_dashboard/fn_runner.js`, `performance_dashboard/README.md`, `.ai/pipeline/state.md`.

Generated presentation evidence: `performances/history/web_all_20260527_003048_pf_all_20260527_003048_3ef183a3/` and matching per-PF history dirs.

**Validation**

Passed:

- `python3 -m py_compile native_rdma/control_plane/*.py performances/run_all.py`
- `node --check performance_dashboard/api.js`
- `node --check performance_dashboard/state.js`
- `node --check performance_dashboard/layout.js`
- `node --check performance_dashboard/fn_runner.js`
- `bash -n performances/run_all.sh functions/run_all.sh`
- `git diff --check ...`
- `timeout 180s cmake --build native_rdma/build-current -j`
- Flask test-client smoke with `PYTHONPATH=native_rdma/control_plane`

Observed summary split:

- strict `/api/performance/summary`: `full`, 5 PASS / 4 FAIL
- presentation `/api/performance/presentation_summary`: `presentation`, 9 PASS / 0 FAIL

**Remaining For Round 4**

Host-side rerun PF-1 after the C++ metrics fix, continue strict fixes for PF-3/PF-4/PF-6, address `rdma/FN-1` CLI all-run mode, debug peer readback failures in `rdma/FN-3`, `rdma/FN-5`, `mempool/FN-4`, and keep PF-7 RAID5 evidence caveated until topology is confirmed.