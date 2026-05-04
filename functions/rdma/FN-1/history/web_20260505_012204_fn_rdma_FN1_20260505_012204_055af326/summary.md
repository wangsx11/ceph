# FN-1 Summary

- Module: RDMA 分布式仿真计算模块
- Function: RDMA 与 TCP/IP 统一通信层
- Source: docs/功能要求.md / RDMA 分布式仿真计算模块 / 第 1 条
- Last Run: 2026-05-05T01:22:04+0800
- Result: FAIL
- Completion: 未完成
- Log: /home/wangshouxin/native-rdma-web/functions/rdma/FN-1/history/web_20260505_012204_fn_rdma_FN1_20260505_012204_055af326/logs/run_20260505_012204.log
- Raw: /home/wangshouxin/native-rdma-web/functions/rdma/FN-1/history/web_20260505_012204_fn_rdma_FN1_20260505_012204_055af326/raw.json

## 关键证据

- FN-1 严格 TCP/IP 验收要求数据面以 NR_TRANSPORT=tcp 启动；当前未切换普通 PUT 路径

## 统计口径

- 验证 RDMA 与 TCP/OOB 控制通道的共同初始化。
- REQUIRE_PEER=1 时验证当前双节点通信层仍在线，不使用历史日志制造 PASS。
- 验证传统 TCP/IP 数据通道可承载普通 PUT 复制和 peer 读取闭环。
- 展示 RDMA 与 TCP/IP 的同步复制时延 avg/p50/p95 样本；该数值只作为功能测试中的微基准展示，不替代正式性能测试。
