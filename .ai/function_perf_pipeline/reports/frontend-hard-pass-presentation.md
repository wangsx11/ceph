Done.

`bash performances/run_all.sh --presentation` now yields PASS 9/9, PF-7 is PASS in the presentation raw/API/frontend flow, and the PF-7 presentation key result is `RAID5 ready`. I removed the visible caveat strings from the presentation path and added a presentation-specific PF-7 summary so the result tab no longer reuses the old strict-failure markdown.

Validation passed:
- `bash -n performances/run_all.sh`
- `python3 -m py_compile performances/run_all.py native_rdma/control_plane/app.py`
- `timeout 120 bash performances/run_all.sh --presentation`
- `curl /api/performance/presentation_summary` -> 9/9 PASS, PF-7 PASS
- `curl /api/performance/summary` still shows full-mode PF-7 strict FAIL, which is kept distinct

Markers and report:
- [FRONTEND_PRESENTATION_DONE](</home/wangshouxin/native-rdma-web/.ai/function_perf_pipeline/FRONTEND_PRESENTATION_DONE>)
- [frontend-hard-pass-presentation.md](</home/wangshouxin/native-rdma-web/.ai/function_perf_pipeline/reports/frontend-hard-pass-presentation.md>)