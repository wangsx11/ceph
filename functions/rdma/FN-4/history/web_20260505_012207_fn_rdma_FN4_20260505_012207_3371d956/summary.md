# FN-4 Summary

- Module: RDMA 分布式仿真计算模块
- Function: CPU 与 GPU 高速直通访问
- Source: docs/功能要求.md / RDMA 分布式仿真计算模块 / 第 4 条
- Last Run: 2026-05-05T01:22:07+0800
- Result: FAIL
- Completion: 未完成
- Log: /home/wangshouxin/native-rdma-web/functions/rdma/FN-4/history/web_20260505_012207_fn_rdma_FN4_20260505_012207_3371d956/logs/run_20260505_012207.log
- Raw: /home/wangshouxin/native-rdma-web/functions/rdma/FN-4/history/web_20260505_012207_fn_rdma_FN4_20260505_012207_3371d956/raw.json

## 关键证据

- peer GPU MR 未启用，不能执行 GPUDirect RDMA

## 统计口径

- 验证 xfusion4 NVIDIA GPU、CUDA、nvidia_peermem 与 RDMA 设备可用。
- 验证 GPU buffer 由 cudaMalloc 分配并注册为 RDMA MR。
- 验证 CPU 只提交 RDMA WR，payload 经 RNIC 进入 GPU 显存；不把普通 CPU slab、TCP 或 cudaMemcpy 全量 payload 等同为 GPU Direct 验收。
