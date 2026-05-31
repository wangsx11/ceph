# FN-4 Summary

- Module: 一致性总线内存池化仿真计算模块
- Function: 跨节点内存自适应分配与热数据迁移
- Source: docs/功能要求.md / 一致性总线内存池化仿真计算模块 / 第 4 条
- Last Run: 2026-05-07T23:48:06+0800
- Result: SKIP
- Completion: 未完成
- Log: /home/wangshouxin/native-rdma-web/functions/mempool/FN-4/history/web_20260507_234806_fn_mempool_FN4_20260507_234806_1bc98402/logs/run_20260507_234806.log
- Raw: /home/wangshouxin/native-rdma-web/functions/mempool/FN-4/history/web_20260507_234806_fn_mempool_FN4_20260507_234806_1bc98402/raw.json

## 关键证据

- REQUIRE_PEER=1 且 peer_alive=false，跳过需要双节点的验证

## 统计口径

- 验证 RDMA 本地/远端内存自适应放置和热点数据本地化迁移。
- peer 未在线时按 SKIP 处理，不用存储层 NVMe/HDD demote 冒充跨节点内存迁移。
- 不统计迁移收益或吞吐性能。
