# FN-2 Summary

- Module: 一致性总线内存池化仿真计算模块
- Function: 分布式内存池 API
- Source: docs/功能要求.md / 一致性总线内存池化仿真计算模块 / 第 2 条
- Last Run: 2026-05-05T01:22:10+0800
- Result: FAIL
- Completion: 未完成
- Log: /home/wangshouxin/native-rdma-web/functions/mempool/FN-2/history/web_20260505_012210_fn_mempool_FN2_20260505_012210_605d5148/logs/run_20260505_012210.log
- Raw: /home/wangshouxin/native-rdma-web/functions/mempool/FN-2/history/web_20260505_012210_fn_mempool_FN2_20260505_012210_605d5148/raw.json

## 关键证据

- RPC_TCP_GET_PEER 返回失败: {'ok': False, 'transport': 'tcp', 'err': 'not found', 'tcp_ns': 197812}

## 统计口径

- 验证数据面 UDS API 闭环，不只验证 Flask 参数解析。
- 验证普通 PUT API 屏蔽底层 RDMA 复制细节，但实际落到 C++ 数据面和 peer 副本。
- 不统计 API 吞吐或延迟性能。
