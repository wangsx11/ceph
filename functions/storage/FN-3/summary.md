# FN-3 Summary

- Module: 多级异构的高效能存储模块
- Function: 多策略预取机制
- Source: docs/功能要求.md / 多级异构的高效能存储模块 / 第 3 条
- Last Run: 2026-05-27T14:12:56+0800
- Result: PASS
- Completion: 完成
- Log: /home/wangshouxin/native-rdma-web/functions/storage/FN-3/logs/run_20260527_141255.log
- Raw: /home/wangshouxin/native-rdma-web/functions/storage/FN-3/raw.json

## 关键证据

- stride 预取执行成功: predicted=fn_prefetch_stride__1779862376030_3849178_4, GET hit=local
- Markov 预取执行成功: predicted=fn_prefetch_markov_1779862376032_3849178_Bkey, GET hit=local
- 预取统计增加: loaded 0->2, hits 0->2

## 统计口径

- 验证 stride/Markov 预测策略。
- 验证预测对象的实际预取加载和后续命中。
- 不统计预取带来的性能提升。
