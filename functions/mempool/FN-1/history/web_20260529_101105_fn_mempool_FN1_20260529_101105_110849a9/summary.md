# FN-1 Summary

- Module: 一致性总线内存池化仿真计算模块
- Function: RDMA 语义远程内存访问与零拷贝
- Source: docs/功能要求.md / 一致性总线内存池化仿真计算模块 / 第 1 条
- Last Run: 2026-05-29T10:11:05+0800
- Result: PASS
- Completion: 完成
- Log: /home/wangshouxin/native-rdma-web/functions/mempool/FN-1/history/web_20260529_101105_fn_mempool_FN1_20260529_101105_110849a9/logs/run_20260529_101105.log
- Raw: /home/wangshouxin/native-rdma-web/functions/mempool/FN-1/history/web_20260529_101105_fn_mempool_FN1_20260529_101105_110849a9/raw.json

## 关键证据

- RPC_KV_PUT_RDMA 走 RDMA: transport=rdma degraded=False repl_ns=46615
- 远端 slab 元数据有效: base=139677611638784 len=4294967296 rkey=71936 qps=32
- offset/size 在 peer slab 范围内: offset=4190208 size=20
- RPC_TCP_GET_PEER 从 peer 读回同一 value: key=fn_zero_copy_1780020665653_3196374

## 统计口径

- 验证可观测的 RDMA WRITE 复制路径，不允许 TCP transport 或本地 degraded 写入冒充。
- 验证 peer 端远程内存实际包含写入对象。
- 零拷贝以用户态注册 slab、peer rkey、远端 offset 范围和 RDMA 完成时延作为当前证据。
