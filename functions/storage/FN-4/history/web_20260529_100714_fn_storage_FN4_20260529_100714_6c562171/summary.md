# FN-4 Summary

- Module: 多级异构的高效能存储模块
- Function: 可配置压缩与去重
- Source: docs/功能要求.md / 多级异构的高效能存储模块 / 第 4 条
- Last Run: 2026-05-29T10:07:14+0800
- Result: FAIL
- Completion: 未完成
- Log: /home/wangshouxin/native-rdma-web/functions/storage/FN-4/history/web_20260529_100714_fn_storage_FN4_20260529_100714_6c562171/logs/run_20260529_100714.log
- Raw: /home/wangshouxin/native-rdma-web/functions/storage/FN-4/history/web_20260529_100714_fn_storage_FN4_20260529_100714_6c562171/raw.json

## 关键证据

- demote 到 HDD 后压缩统计未增加

## 统计口径

- 验证 ZSTD/LZ4 压缩统计可观测。
- 验证运行时 SHA-256 指纹去重统计可观测。
- 不统计压缩/去重带来的性能收益。
