# FN-3 Summary

- Module: 多级异构的高效能存储模块
- Function: 多策略预取机制
- Source: docs/功能要求.md / 多级异构的高效能存储模块 / 第 3 条
- Last Run: 2026-05-29T10:08:04+0800
- Result: PASS
- Completion: 完成
- Log: /home/wangshouxin/native-rdma-web/functions/storage/FN-3/history/web_20260529_100804_fn_storage_FN3_20260529_100804_45c83068/logs/run_20260529_100804.log
- Raw: /home/wangshouxin/native-rdma-web/functions/storage/FN-3/history/web_20260529_100804_fn_storage_FN3_20260529_100804_45c83068/raw.json

## 关键证据

- stride 预取执行成功: predicted=fn_prefetch_stride__1780020484968_3191092_4, GET hit=local
- Markov 预取执行成功: predicted=fn_prefetch_markov_1780020484971_3191092_Bkey, GET hit=local
- 预取统计增加: loaded 2->4, hits 2->4

## 统计口径

- 验证 stride/Markov 预测策略。
- 验证预测对象的实际预取加载和后续命中。
- 不统计预取带来的性能提升。
