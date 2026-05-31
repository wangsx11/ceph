**Round 1 Diagnosis Complete**

Updated `.ai/function_perf_pipeline/state.md`. `BLOCKED` and `DONE` are absent.

Key findings:
- Direct sandbox still cannot see RDMA devices: `/dev/infiniband` empty, `ibv_devinfo` says no IB devices. Hardware checks should stay host-side via `ssh xfusion3`.
- Current function aggregate: `16 PASS / 0 FAIL / 1 WAIVED`. The only non-pass is `rdma/FN-4`.
- FN-4 is not a missing-hardware issue: xfusion4 has NVIDIA GPUs, CUDA 12.6, `nvidia_peermem`, and `mlx5_0`. Current data planes report `gdr_requested=false`, `gdr_compiled=false`, and no GPU MR, so this is a GDR startup/build-mode gap until tested with `NR_GDR_ENABLE=1`.
- Current full performance aggregate: `5/9` strict pass. Failing/non-strict items are PF-3, PF-4, PF-6, and PF-7 strict RAID5 confirmation.
- Presentation performance mode reports 9/9 by preserving evidence and running no live PFs. It is bounded for display, but does not replace full performance acceptance.
- Risky/slow commands: unrestricted `bash performances/run_all.sh`, PF-1, PF-6, PF-7, and to a lesser degree PF-3/PF-4. These need timeouts and SSH probes.

Round 2 priority: start GDR mode host-side with SSH probes, then run `REQUIRE_PEER=1 bash functions/rdma/FN-4/run.sh`; fix startup/CUDA/MR/OOB issues as needed, then run the function suite twice.

Round 3 priority: add guarded performance execution, then fix PF-3 QoS gain, PF-4 scenario B, PF-6 bandwidth, and PF-7 strict RAID5 semantics.

Validation commands included:
- `timeout 10 ssh xfusion3 hostname`
- `timeout 10 ssh xfusion4 hostname`
- xfusion4 non-invasive GPU/CUDA/peermem/RDMA probe
- host-side UDS `RPC_CLUSTER_STATUS` and `RPC_GDR_STATUS` on xfusion3/xfusion4
- local `ls /dev/infiniband` and `ibv_devinfo`
- `jq`/`rg`/`sed` inspection of function and performance raw/summary files

Changed file:
- `.ai/function_perf_pipeline/state.md`