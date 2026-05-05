# FN-3 Summary

- Module: 一致性总线内存池化仿真计算模块
- Function: 内存池统一命名机制
- Source: docs/功能要求.md / 一致性总线内存池化仿真计算模块 / 第 3 条
- Last Run: 2026-05-05T06:38:03+0800
- Result: PASS
- Completion: 完成
- Log: /home/wangshouxin/native-rdma-web/functions/mempool/FN-3/history/web_20260505_063803_fn_mempool_FN3_20260505_063803_d7e5bb3e/logs/run_20260505_063803.log
- Raw: /home/wangshouxin/native-rdma-web/functions/mempool/FN-3/history/web_20260505_063803_fn_mempool_FN3_20260505_063803_d7e5bb3e/raw.json

## 关键证据

- 统一 pool 名称有效: local=default/slab1k remote=default/slab1k peer_id=192.168.0.214
- 本地 registry 与 cluster slab 元数据一致: base=140526390919168 len=4294967296 lkey=96256 rkey=96256
- 远端 registry 与 OOB peer slab 元数据一致: base=139687186669568 len=4294967296 rkey=71936 qps=32

## 统计口径

- 验证共享内存区域统一命名、PoolRegistry 本地/远端登记和 RDMA 元数据交换。
- peer 未在线时按 SKIP 处理，不用历史 OOB 字段制造 PASS。
- 不验证多 pool 枚举或动态 pool 创建。
