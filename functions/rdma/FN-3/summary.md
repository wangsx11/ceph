# FN-3 Summary

- Module: RDMA 分布式仿真计算模块
- Function: 流量优先级机制
- Source: docs/功能要求.md / RDMA 分布式仿真计算模块 / 第 3 条
- Last Run: 2026-05-03T23:41:53+0800
- Result: PASS
- Completion: 完成
- Log: /home/wangshouxin/native-rdma-web/functions/rdma/FN-3/logs/run_20260503_234153.log
- Raw: /home/wangshouxin/native-rdma-web/functions/rdma/FN-3/raw.json

## 关键证据

- 高低优先级 PUT 均成功，QosSched 日志存在: /home/wangshouxin/native-rdma-web/native_rdma/logs/dp_A.log

## 统计口径

- 验证高低优先级路径可用。
- 不验证 22% 效率提升，性能归入 performances/PF-3。
