# FN-1 Summary

- Module: RDMA 分布式仿真计算模块
- Function: RDMA 与 TCP/IP 统一通信层
- Source: docs/功能要求.md / RDMA 分布式仿真计算模块 / 第 1 条
- Last Run: 2026-05-05T05:33:31+0800
- Result: PASS
- Completion: 完成
- Log: /home/wangshouxin/native-rdma-web/functions/rdma/FN-1/history/web_20260505_053314_fn_rdma_FN1_20260505_053314_a6bd95e0/logs/run_20260505_053314.log
- Raw: /home/wangshouxin/native-rdma-web/functions/rdma/FN-1/history/web_20260505_053314_fn_rdma_FN1_20260505_053314_a6bd95e0/raw.json

## 关键证据

- 最近一次数据面启动日志包含 RDMA QP、TcpFallback 和 OOB exchange 证据: /home/wangshouxin/native-rdma-web/native_rdma/logs/dp_A.log
- peer_alive=True peer_num_qp=32 peer_slab_rkey=71936
- TCP 协议切换闭环成功: RPC_KV_PUT transport=tcp -> RPC_TCP_GET_PEER size=19
- RDMA/TCP 复制时延对比: RDMA avg=18.084us p95=14.639us; TCP avg=224.252us p95=274.625us; samples=8

## 统计口径

- 验证 RDMA 与 TCP/OOB 控制通道的共同初始化。
- REQUIRE_PEER=1 时验证当前双节点通信层仍在线，不使用历史日志制造 PASS。
- 验证传统 TCP/IP 数据通道可承载普通 PUT 复制和 peer 读取闭环。
- 展示 RDMA 与 TCP/IP 的同步复制时延 avg/p50/p95 样本；该数值只作为功能测试中的微基准展示，不替代正式性能测试。
