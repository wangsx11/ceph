# FN-1 Summary

- Module: RDMA 分布式仿真计算模块
- Function: RDMA 与 TCP/IP 统一通信层
- Source: docs/功能要求.md / RDMA 分布式仿真计算模块 / 第 1 条
- Last Run: 2026-05-04T13:21:30+0800
- Result: PASS
- Completion: 完成
- Log: /home/wangshouxin/native-rdma-web/functions/rdma/FN-1/logs/run_20260504_132130.log
- Raw: /home/wangshouxin/native-rdma-web/functions/rdma/FN-1/raw.json

## 关键证据

- 最近一次数据面启动日志包含 RDMA QP、TcpFallback 和 OOB exchange 证据: /home/wangshouxin/native-rdma-web/native_rdma/logs/dp_A.log
- peer_alive=True peer_num_qp=32 peer_slab_rkey=87040
- TCP 协议切换闭环成功: RPC_KV_PUT transport=tcp -> RPC_TCP_GET_PEER size=19
- RDMA/TCP 复制时延对比: RDMA avg=23005ns p95=21657ns; TCP avg=199431ns p95=215146ns; samples=8

## 统计口径

- 验证 RDMA 与 TCP/OOB 控制通道的共同初始化。
- REQUIRE_PEER=1 时验证当前双节点通信层仍在线，不使用历史日志制造 PASS。
- 验证传统 TCP/IP 数据通道可承载普通 PUT 复制和 peer 读取闭环。
- 展示 RDMA 与 TCP/IP 的同步复制时延 avg/p50/p95 样本；该数值只作为功能测试中的微基准展示，不替代正式性能测试。
