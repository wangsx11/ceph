# FN-3 Summary

- Module: RDMA 分布式仿真计算模块
- Function: 流量优先级机制
- Source: docs/功能要求.md / RDMA 分布式仿真计算模块 / 第 3 条
- Last Run: 2026-05-05T06:37:11+0800
- Result: FAIL
- Completion: 未完成
- Log: /home/wangshouxin/native-rdma-web/functions/rdma/FN-3/history/web_20260505_063711_fn_rdma_FN3_20260505_063711_c784718d/logs/run_20260505_063711.log
- Raw: /home/wangshouxin/native-rdma-web/functions/rdma/FN-3/history/web_20260505_063711_fn_rdma_FN3_20260505_063711_c784718d/raw.json

## 关键证据

- 高低优先级 RDMA PUT 后 peer 读回失败

## 统计口径

- 验证高低优先级路径可用且映射到不同 RDMA QP 分组。
- 验证 peer 端读回闭环，不使用 peer 离线本地降级写结果冒充 RDMA QoS 数据面。
- 不验证 22% 效率提升，性能归入 performances/PF-3。
