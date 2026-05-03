# FN-6 Summary

- Module: 一致性总线内存池化仿真计算模块
- Function: 内存池高可靠机制
- Source: docs/功能要求.md / 一致性总线内存池化仿真计算模块 / 第 6 条
- Last Run: 2026-05-03T23:41:54+0800
- Result: PASS
- Completion: 部分完成
- Log: /home/wangshouxin/native-rdma-web/functions/mempool/FN-6/logs/run_20260503_234154.log
- Raw: /home/wangshouxin/native-rdma-web/functions/mempool/FN-6/raw.json

## 关键证据

- HA 字段完备: peer_alive=False degraded_puts=19 degraded_bytes=4255
- 默认未执行主动 kill peer；完整演练需 ALLOW_DESTRUCTIVE=1 且提供 PEER_SSH/PEER_DP_PATH

## 统计口径

- 默认不 kill peer。
- ALLOW_DESTRUCTIVE=1 且提供 peer 参数时才主动演练故障降级。
