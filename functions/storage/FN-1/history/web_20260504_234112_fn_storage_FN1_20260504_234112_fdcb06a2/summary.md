# FN-1 Summary

- Module: 多级异构的高效能存储模块
- Function: 仿真引擎异构存储统一访问接口
- Source: docs/功能要求.md / 多级异构的高效能存储模块 / 第 1 条
- Last Run: 2026-05-04T23:41:12+0800
- Result: FAIL
- Completion: 未完成
- Log: /home/wangshouxin/native-rdma-web/functions/storage/FN-1/history/web_20260504_234112_fn_storage_FN1_20260504_234112_fdcb06a2/logs/run_20260504_234112.log
- Raw: /home/wangshouxin/native-rdma-web/functions/storage/FN-1/history/web_20260504_234112_fn_storage_FN1_20260504_234112_fdcb06a2/raw.json

## 关键证据

- RPC_KV_PUT hdd probe 返回失败: {'ok': False, 'err': 'slab oom'}

## 统计口径

- 验证统一层级状态接口可用。
- 验证 DRAM 写入、NVMe/HDD demote 和读回提升闭环。
- 不统计读写吞吐或层级带宽，性能归入 performances/PF-6。
