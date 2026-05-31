Done.

FN-3 was a peer readback visibility race: the RDMA PUT completed, but the peer index could lag the immediate TCP verification GET. I fixed that in [functions/common/checks.py](/home/wangshouxin/native-rdma-web/functions/common/checks.py:1032) by keeping the peer readback requirement and adding a bounded retry with sampled attempts.

I also split PF-7 presentation from strict acceptance in [performances/run_all.py](/home/wangshouxin/native-rdma-web/performances/run_all.py:1), [native_rdma/control_plane/app.py](/home/wangshouxin/native-rdma-web/native_rdma/control_plane/app.py:1), and [performance_dashboard/fn_result.js](/home/wangshouxin/native-rdma-web/performance_dashboard/fn_result.js:1). Presentation now shows RAID5 capability evidence without claiming strict `raid5_confirmed=true`. Full PF-7 stays strict FAIL.

Validation passed:
- `timeout 10 ssh xfusion4 hostname` before and after
- two consecutive `bash functions/run_all.sh` runs on `xfusion3`
- `timeout 120 bash performances/run_all.sh --presentation`
- API checks for presentation and full performance summaries

The pipeline state is updated in [.ai/function_perf_pipeline/state.md](/home/wangshouxin/native-rdma-web/.ai/function_perf_pipeline/state.md) and the completion marker is in [.ai/function_perf_pipeline/DONE](/home/wangshouxin/native-rdma-web/.ai/function_perf_pipeline/DONE). Final report: [.ai/function_perf_pipeline/reports/final-repair-no-history.md](/home/wangshouxin/native-rdma-web/.ai/function_perf_pipeline/reports/final-repair-no-history.md).