# PF-9 Summary

- Metric: 仿真引擎内存池化能力
- Source: `docs/性能要求.md` 第 9 条
- Generated At: 2026-05-05T05:39:40+0800
- Key Result: overhead=0.0%, savings=11.47%, scale=32.49%
- Threshold: 性能损失 <= 5%；内存节省 >= 7%；分配/释放吞吐提升 >= 20%
- Result: PASS
- Result Dir: /home/wangshouxin/native-rdma-web/performances/PF-9/history/web_20260505_053935_pf_PF9_20260505_053935_b8e6f69f
- Raw JSON: /home/wangshouxin/native-rdma-web/performances/PF-9/history/web_20260505_053935_pf_PF9_20260505_053935_b8e6f69f/raw.json
- Raw CSV: 未生成
- Run Log: /home/wangshouxin/native-rdma-web/performances/PF-9/history/web_20260505_053935_pf_PF9_20260505_053935_b8e6f69f/logs/run.log

## 关键统计值

| Key | Value |
|---|---:|
| `overhead_pct` | 0.0 |
| `savings_pct` | 11.47 |
| `scale_gain_pct` | 32.49 |
| `threads_multi` | 8 |
| `malloc_ops_1t` | 15687528 |
| `slab_ops_1t` | 47186681 |
| `malloc_ops_Nt` | 14405460 |
| `slab_ops_Nt` | 19085832 |
| `malloc_live_rss_kb` | 303592 |
| `slab_live_rss_kb` | 268784 |
| `live_objects` | 262144 |
| `live_requested_kb` | 262144 |
| `baseline_metadata_bytes` | 128 |
| `throughput_metadata_bytes` | 16 |
| `malloc_usable_kb` | 296960 |
| `slab_usable_kb` | 263168 |
| `passed_overhead` | True |
| `passed_savings` | True |
| `passed_scale` | True |

## 统计口径

- 测试逻辑由 `native_rdma/tests/performance/perf_09_mempool.sh` 迁移到本 `run.py`。
- 执行 `native_rdma/build/bin/nr_mempool_bench` 并直接记录其 JSON 输出。
- 吞吐测试对比 malloc/free 基线和 slab fast path，并在分配后真实初始化完整 1KB 对象。
- 吞吐基线包含 16B 轻量对象头，避免把未池化路径建模得过重。
- 内存基线为未池化 RDMA 对象记录：每个对象包含 1KB payload 和真实分配的对象/MR 元数据。
- 不使用固定 savings fallback；如果 live RSS 测不到 7% 节省，测试直接失败。
