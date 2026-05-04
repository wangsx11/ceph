# FN-4 Summary

- Module: 一致性总线内存池化仿真计算模块
- Function: 跨节点内存自适应分配与热数据迁移
- Source: docs/功能要求.md / 一致性总线内存池化仿真计算模块 / 第 4 条
- Last Run: 2026-05-05T01:26:04+0800
- Result: PASS
- Completion: 完成
- Log: /home/wangshouxin/native-rdma-web/functions/mempool/FN-4/history/web_20260505_012604_fn_mempool_FN4_20260505_012604_92661606/logs/run_20260505_012604.log
- Raw: /home/wangshouxin/native-rdma-web/functions/mempool/FN-4/history/web_20260505_012604_fn_mempool_FN4_20260505_012604_92661606/raw.json

## 关键证据

- 冷对象自适应放置到远端 RDMA slab: remote_offset=67108864 size=32
- 首次访问保持远端放置并通过 RDMA READ 读取: hit=remote_rdma_read access_count=1
- 热点阈值 3 次访问后迁回本地 slab: local_offset=40923136 rdma_read_ns=11849
- 迁移后普通 RPC_KV_GET 本地命中: hit=local

## 统计口径

- 验证 RDMA 本地/远端内存自适应放置和热点数据本地化迁移。
- peer 未在线时按 SKIP 处理，不用存储层 NVMe/HDD demote 冒充跨节点内存迁移。
- 不统计迁移收益或吞吐性能。
