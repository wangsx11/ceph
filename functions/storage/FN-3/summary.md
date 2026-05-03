# FN-3 Summary

- Module: 多级异构的高效能存储模块
- Function: 多策略预取机制
- Source: docs/功能要求.md / 多级异构的高效能存储模块 / 第 3 条
- Last Run: 2026-05-03T23:41:52+0800
- Result: PASS
- Completion: 完成
- Log: /home/wangshouxin/native-rdma-web/functions/storage/FN-3/logs/run_20260503_234152.log
- Raw: /home/wangshouxin/native-rdma-web/functions/storage/FN-3/raw.json

## 关键证据

- 顺序访问触发 stride 预测: expected=fn_prefetch__1777822912792_29822894 predicted_count=8

## 统计口径

- 验证 stride/Markov 统计与预测接口。
- 不统计预取带来的性能提升。
