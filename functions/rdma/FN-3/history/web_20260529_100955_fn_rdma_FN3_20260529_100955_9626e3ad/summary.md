# FN-3 Summary

- Module: RDMA 分布式仿真计算模块
- Function: 流量优先级机制
- Source: docs/功能要求.md / RDMA 分布式仿真计算模块 / 第 3 条
- Last Run: 2026-05-29T10:09:55+0800
- Result: PASS
- Completion: 完成
- Log: /home/wangshouxin/native-rdma-web/functions/rdma/FN-3/history/web_20260529_100955_fn_rdma_FN3_20260529_100955_9626e3ad/logs/run_20260529_100955.log
- Raw: /home/wangshouxin/native-rdma-web/functions/rdma/FN-3/history/web_20260529_100955_fn_rdma_FN3_20260529_100955_9626e3ad/raw.json

## 关键证据

- QosSched 最近启动日志存在: /home/wangshouxin/native-rdma-web/native_rdma/logs/dp_A.log
- 高优先级 PUT 走 RDMA QP 8，低优先级 PUT 走 RDMA QP 16
- 高低优先级 RDMA PUT 均完成 peer 读回同值校验

## 统计口径

- 验证高低优先级路径可用且映射到不同 RDMA QP 分组。
- 验证 peer 端读回闭环，不使用 peer 离线本地降级写结果冒充 RDMA QoS 数据面。
- 不验证 22% 效率提升，性能归入 performances/PF-3。
