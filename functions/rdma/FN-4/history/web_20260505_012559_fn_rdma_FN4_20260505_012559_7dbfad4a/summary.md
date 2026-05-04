# FN-4 Summary

- Module: RDMA 分布式仿真计算模块
- Function: CPU 与 GPU 高速直通访问
- Source: docs/功能要求.md / RDMA 分布式仿真计算模块 / 第 4 条
- Last Run: 2026-05-05T01:25:59+0800
- Result: WAIVED
- Completion: 硬件/环境豁免
- Log: /home/wangshouxin/native-rdma-web/functions/rdma/FN-4/history/web_20260505_012559_fn_rdma_FN4_20260505_012559_7dbfad4a/logs/run_20260505_012559.log
- Raw: /home/wangshouxin/native-rdma-web/functions/rdma/FN-4/history/web_20260505_012559_fn_rdma_FN4_20260505_012559_7dbfad4a/raw.json

## 关键证据

- peer GPU MR 未启用，当前未满足 GPUDirect RDMA 验收硬件/启动条件；需要 NR_GDR_ENABLE=1、xfusion4 NVIDIA GPU 和 nvidia_peermem/nv_peer_mem 后重跑

## 统计口径

- 验证 xfusion4 NVIDIA GPU、CUDA、nvidia_peermem 与 RDMA 设备可用。
- 验证 GPU buffer 由 cudaMalloc 分配并注册为 RDMA MR。
- 验证 CPU 只提交 RDMA WR，payload 经 RNIC 进入 GPU 显存；不把普通 CPU slab、TCP 或 cudaMemcpy 全量 payload 等同为 GPU Direct 验收。
