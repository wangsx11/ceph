# PF-9 Summary

- Metric: 仿真引擎内存池化能力
- Source: `docs/性能要求.md` 第 9 条
- Generated At: 2026-05-04T00:23:36+0800
- Key Result: overhead=0.0%, savings=8.0%, scale=86.71%
- Threshold: 性能损失 <= 5%；内存节省 >= 7%；分配/释放吞吐提升 >= 20%
- Result: PASS
- Result Dir: /home/wangshouxin/native-rdma-web/performances/PF-9
- Raw JSON: /home/wangshouxin/native-rdma-web/performances/PF-9/raw.json
- Raw CSV: 未生成
- Run Log: /home/wangshouxin/native-rdma-web/performances/PF-9/logs/run.log

## 关键统计值

| Key | Value |
|---|---:|
| `overhead_pct` | 0.0 |
| `savings_pct` | 8.0 |
| `scale_gain_pct` | 86.71 |
| `threads_multi` | 8 |
| `malloc_ops_1t` | 29821184 |
| `slab_ops_1t` | 76055159 |
| `malloc_ops_Nt` | 14090496 |
| `slab_ops_Nt` | 26307858 |
| `passed_overhead` | True |
| `passed_savings` | True |
| `passed_scale` | True |

## 统计口径

- 测试逻辑由 `native_rdma/tests/performance/perf_09_mempool.sh` 迁移到本 `run.py`。
- 执行 `native_rdma/build/bin/nr_mempool_bench` 并直接记录其 JSON 输出。
- 基线与内存池场景使用相同对象大小、线程数、操作数和硬件环境。
