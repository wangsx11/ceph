# FN-1 Summary

- Module: 一致性总线内存池化仿真计算模块
- Function: RDMA 语义远程内存访问与零拷贝
- Source: docs/功能要求.md / 一致性总线内存池化仿真计算模块 / 第 1 条
- Last Run: 2026-05-03T23:41:53+0800
- Result: SKIP
- Completion: 未完成
- Log: /home/wangshouxin/native-rdma-web/functions/mempool/FN-1/logs/run_20260503_234153.log
- Raw: /home/wangshouxin/native-rdma-web/functions/mempool/FN-1/raw.json

## 关键证据

- REQUIRE_PEER=1 且 peer_alive=false，跳过需要双节点的验证

## 统计口径

- 验证可观测的 RDMA WRITE 复制路径。
- 零拷贝以用户态 slab 偏移、rkey 和 repl_ns 作为当前证据。
