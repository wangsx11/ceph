# FN-6 Summary

- Module: 一致性总线内存池化仿真计算模块
- Function: 内存池高可靠机制
- Source: docs/功能要求.md / 一致性总线内存池化仿真计算模块 / 第 6 条
- Last Run: 2026-05-07T13:39:56+0800
- Result: PASS
- Completion: 完成
- Log: /home/wangshouxin/native-rdma-web/functions/mempool/FN-6/history/web_20260507_133938_fn_mempool_FN6_20260507_133938_5b554bbb/logs/run_20260507_133938.log
- Raw: /home/wangshouxin/native-rdma-web/functions/mempool/FN-6/history/web_20260507_133938_fn_mempool_FN6_20260507_133938_5b554bbb/raw.json

## 关键证据

- 主动故障演练成功: peer_alive true->false, degraded_puts 0->1
- 故障期间 RPC_KV_PUT 返回 degraded=true 且本地 RPC_KV_GET 读回: key=fn_ha_degraded_1778132382574_1174263
- 恢复命令执行后 peer_alive=true，后续 PUT 重新走 RDMA 非降级复制并可从 peer 读回

## 统计口径

- 默认不 kill peer，仅做非破坏性字段检查并标记部分完成。
- 完整验收需 ALLOW_DESTRUCTIVE=1、PEER_SSH、PEER_DP_PATH 和 FN6_RECOVERY_CMD。
- 验证 peer 失联期间本节点继续提供本地 PUT/GET 可用性；不宣称无需重启即可自动重新 OOB/QP 握手。
