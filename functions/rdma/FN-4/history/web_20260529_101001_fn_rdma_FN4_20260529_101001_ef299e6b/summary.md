# FN-4 Summary

- Module: RDMA 分布式仿真计算模块
- Function: CPU 与 GPU 高速直通访问
- Source: docs/功能要求.md / RDMA 分布式仿真计算模块 / 第 4 条
- Last Run: 2026-05-29T10:10:27+0800
- Result: PASS
- Completion: 完成
- Log: /home/wangshouxin/native-rdma-web/functions/rdma/FN-4/history/web_20260529_101001_fn_rdma_FN4_20260529_101001_ef299e6b/logs/run_20260529_101001.log
- Raw: /home/wangshouxin/native-rdma-web/functions/rdma/FN-4/history/web_20260529_101001_fn_rdma_FN4_20260529_101001_ef299e6b/raw.json

## 关键证据

- xfusion4 证明 NVIDIA GPU、CUDA、nvidia_peermem/nv_peer_mem 与 mlx5_0 RDMA 设备可用
- RPC_GDR_STATUS peer GPU MR 有效: base=139934765678592 len=67108864 rkey=87042
- A->B RPC_GDR_WRITE 写入 GPU MR 4096B，write_ns=72688，degraded=false
- xfusion4 CUDA kernel 校验 GPU buffer 通过，checksum=522240 validate_ns=263699
- A 侧 RPC_GDR_READBACK 读回校验通过，read_ns=26952 checksum=522240

## 统计口径

- 验证 xfusion4 NVIDIA GPU、CUDA、nvidia_peermem 与 RDMA 设备可用。
- 验证 GPU buffer 由 cudaMalloc 分配并注册为 RDMA MR。
- 验证 CPU 只提交 RDMA WR，payload 经 RNIC 进入 GPU 显存；不把普通 CPU slab、TCP 或 cudaMemcpy 全量 payload 等同为 GPU Direct 验收。
