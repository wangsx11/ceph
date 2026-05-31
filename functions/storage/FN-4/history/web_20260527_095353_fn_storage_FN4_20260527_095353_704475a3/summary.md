# FN-4 Summary

- Module: 多级异构的高效能存储模块
- Function: 可配置压缩与去重
- Source: docs/功能要求.md / 多级异构的高效能存储模块 / 第 4 条
- Last Run: 2026-05-27T09:53:53+0800
- Result: PASS
- Completion: 完成
- Log: /home/wangshouxin/native-rdma-web/functions/storage/FN-4/history/web_20260527_095353_fn_storage_FN4_20260527_095353_704475a3/logs/run_20260527_095353.log
- Raw: /home/wangshouxin/native-rdma-web/functions/storage/FN-4/history/web_20260527_095353_fn_storage_FN4_20260527_095353_704475a3/raw.json

## 关键证据

- 压缩统计增加: objects 0->1, saved_bytes 0->4077
- 去重统计增加: duplicate_objects 0->1, saved_bytes 0->19
- HDD 读回闭环成功: A hit=hdd_promote, B hit=hdd_promote

## 统计口径

- 验证 ZSTD/LZ4 压缩统计可观测。
- 验证运行时 SHA-256 指纹去重统计可观测。
- 不统计压缩/去重带来的性能收益。
