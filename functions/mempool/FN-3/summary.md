# FN-3 Summary

- Module: 一致性总线内存池化仿真计算模块
- Function: 内存池统一命名机制
- Source: docs/功能要求.md / 一致性总线内存池化仿真计算模块 / 第 3 条
- Last Run: 2026-05-03T23:41:53+0800
- Result: SKIP
- Completion: 未完成
- Log: /home/wangshouxin/native-rdma-web/functions/mempool/FN-3/logs/run_20260503_234153.log
- Raw: /home/wangshouxin/native-rdma-web/functions/mempool/FN-3/raw.json

## 关键证据

- REQUIRE_PEER=1 且 peer_alive=false，跳过需要双节点的验证

## 统计口径

- 验证共享内存区域命名和 RDMA 元数据交换。
- peer 未在线时按 SKIP 处理。
