# PF-4 Summary

- Metric: RDMA 网络环境下对象数据聚合传输能力
- Source: `docs/性能要求.md` 第 4 条
- Generated At: 2026-05-05T01:36:42+0800
- Threshold: 场景 A (1000×100) <= 200ms；场景 B (100×1000) <= 100ms
- Result: PASS
- Result Dir: /home/wangshouxin/native-rdma-web/performances/PF-4/history/web_20260505_013642_pf_PF4_20260505_013642_f0e43b35
- Raw JSON: /home/wangshouxin/native-rdma-web/performances/PF-4/history/web_20260505_013642_pf_PF4_20260505_013642_f0e43b35/raw.json
- Run Log: /home/wangshouxin/native-rdma-web/performances/PF-4/history/web_20260505_013642_pf_PF4_20260505_013642_f0e43b35/logs/run.log

## 场景 A: 1000 批次 × 100 个 1KB 对象

| Key | Value |
|---|---:|
| `elapsed_ms` | 64.99 |
| `ops_ok` | 100000 |
| `ops_fail` | 0 |
| `threshold` | <= 200ms |
| `passed` | True |

## 场景 B: 100 批次 × 1000 个 1KB 对象

| Key | Value |
|---|---:|
| `elapsed_ms` | 49.74 |
| `ops_ok` | 100000 |
| `ops_fail` | 0 |
| `threshold` | <= 100ms |
| `passed` | True |

## 统计口径

- 使用 nr_bench --count 模式，精确执行指定数量的串行 RPC_KV_PUT_BATCH 调用。
- 场景 A：1000 次 batch 调用，每次 100 个 1KB 对象。
- 场景 B：100 次 batch 调用，每次 1000 个 1KB 对象。
- 计时从第一批提交到最后一批响应返回。
- 不统计构建、脚本启动、环境启动和 warmup 时间。
