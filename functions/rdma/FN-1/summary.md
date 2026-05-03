# FN-1 Summary

- Module: RDMA 分布式仿真计算模块
- Function: RDMA 与 TCP/IP 统一通信层
- Source: docs/功能要求.md / RDMA 分布式仿真计算模块 / 第 1 条
- Last Run: 2026-05-03T23:41:53+0800
- Result: PASS
- Completion: 完成
- Log: /home/wangshouxin/native-rdma-web/functions/rdma/FN-1/logs/run_20260503_234153.log
- Raw: /home/wangshouxin/native-rdma-web/functions/rdma/FN-1/raw.json

## 关键证据

- 日志包含 RDMA QP 和 TCP fallback/OOB 证据: /home/wangshouxin/native-rdma-web/native_rdma/logs/dp_A.log
- peer_num_qp=32 peer_alive=False

## 统计口径

- 验证 RDMA 与 TCP 控制通道的共同初始化。
- 不单独压测通信延迟或带宽。
