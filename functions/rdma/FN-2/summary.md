# FN-2 Summary

- Module: RDMA 分布式仿真计算模块
- Function: 聚合数据传输
- Source: docs/功能要求.md / RDMA 分布式仿真计算模块 / 第 2 条
- Last Run: 2026-05-04T13:48:05+0800
- Result: PASS
- Completion: 完成
- Log: /home/wangshouxin/native-rdma-web/functions/rdma/FN-2/logs/run_20260504_134805.log
- Raw: /home/wangshouxin/native-rdma-web/functions/rdma/FN-2/raw.json

## 关键证据

- RPC_KV_PUT_BATCH 成功: ok_n=8/8 replicated_n=8/8
- 批量 RDMA peer 读回成功: RPC_TCP_GET_PEER 8/8 同值
- 最近一次启动日志包含 BatchAggregator/RDMA QP/OOB 证据: /home/wangshouxin/native-rdma-web/native_rdma/logs/dp_A.log

## 统计口径

- 验证批量小对象 RDMA 传输功能路径可用。
- 验证 peer 端读回闭环，不使用 peer 离线本地批量写结果冒充 RDMA 聚合传输。
- 不统计批处理吞吐、延迟阈值或 doorbell 聚合性能收益。
