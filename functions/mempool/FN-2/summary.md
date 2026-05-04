# FN-2 Summary

- Module: 一致性总线内存池化仿真计算模块
- Function: 分布式内存池 API
- Source: docs/功能要求.md / 一致性总线内存池化仿真计算模块 / 第 2 条
- Last Run: 2026-05-04T15:17:54+0800
- Result: PASS
- Completion: 完成
- Log: /home/wangshouxin/native-rdma-web/functions/mempool/FN-2/logs/run_20260504_151753.log
- Raw: /home/wangshouxin/native-rdma-web/functions/mempool/FN-2/raw.json

## 关键证据

- UDS 封装 API 闭环成功: RPC_KV_PUT -> RPC_KV_GET key=fn_pool_api_1777879074056_475467 hit=local size=26
- RPC_KV_PUT 屏蔽底层 RDMA 细节但返回 transport=rdma degraded=False offset=3141632
- 本地与 peer slab/MR 元数据有效，offset/size 同时落在两端 slab 范围内
- RPC_TCP_GET_PEER 从 peer 读回同一 value，证明分布式内存池 API 的远端副本可见

## 统计口径

- 验证数据面 UDS API 闭环，不只验证 Flask 参数解析。
- 验证普通 PUT API 屏蔽底层 RDMA 复制细节，但实际落到 C++ 数据面和 peer 副本。
- 不统计 API 吞吐或延迟性能。
