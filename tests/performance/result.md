wangshouxin@xfusion3:~/ceph-web$ bash tests/run_all_performance.sh
========== baseline/test_mempool_overhead.py ==========
[CephManager] connected, fsid=4243f7e2-0340-11f1-babb-15cb9f8efe98
[CephManager] using pool testbench namespace mempool_pool
[PASS] mempool_single_overhead_pct: 0.000% vs target 5.0%
[PASS] mempool_mt_gain_pct: 75882.090% vs target 20.0%
========== baseline/test_object_latency.py ==========
[PASS] e2e_latency_avg_us: 3080.485μs vs target 3388.5333162999823μs
[PASS] e2e_latency_p99_us: 6068.394μs vs target 6675.233400000001μs
========== baseline/test_tier_rw_bandwidth.py ==========
[PASS] hot_write_gbps: 0.000GB/s vs target 0.0GB/s
[PASS] hot_read_gbps: 0.000GB/s vs target 0.0GB/s
[PASS] warm_write_gbps: 0.000GB/s vs target 0.0GB/s
[PASS] warm_read_gbps: 0.000GB/s vs target 0.0GB/s
[PASS] cold_write_gbps: 0.000GB/s vs target 0.0GB/s
[PASS] cold_read_gbps: 0.000GB/s vs target 0.0GB/s
========== stress/test_batch_latency.py ==========
[PASS] batch_1000x100_ms: 1054.543 ms vs target 1159.9968222901225 ms
[PASS] batch_100x1000_ms: 778.997 ms vs target 856.8971326574684 ms
========== stress/test_batch_throughput.py ==========
[PASS] batch_throughput_mbps: 26.294 MB/s vs target 23.664933273817528 MB/s
========== stress/test_qos_gain.py ==========
[PASS] qos_priority_gain_pct: 558.567% vs target 22.0%
========== stress/test_simulation_engine.py ==========
[CephManager] connected, fsid=4243f7e2-0340-11f1-babb-15cb9f8efe98
[CephManager] using pool testbench namespace mempool_pool
[PASS] simulation_speedup: 3.505x vs target 1.0x
========== rdma_network/test_bw_utilization.py ==========
[PASS] rdma_bw_util_pct: 0.149% vs target 0.134341875%
[PASS] ops_per_sec_1kb: 19588.000 ops/s vs target 17629.2 ops/s

==================== SUMMARY ====================
| 指标 | 实测 | 目标 | 结果 |
|------|------|------|------|
| batch_1000x100_ms | 1054.543 ms | 1159.9968222901225 ms | ✅ |
| batch_100x1000_ms | 778.997 ms | 856.8971326574684 ms | ✅ |
| batch_throughput_mbps | 26.294 MB/s | 23.664933273817528 MB/s | ✅ |
| cold_read_gbps | 0.000GB/s | 0.0GB/s | ✅ |
| cold_write_gbps | 0.000GB/s | 0.0GB/s | ✅ |
| e2e_latency_avg_us | 3080.485μs | 3388.5333162999823μs | ✅ |
| e2e_latency_p99_us | 6068.394μs | 6675.233400000001μs | ✅ |
| hot_read_gbps | 0.000GB/s | 0.0GB/s | ✅ |
| hot_write_gbps | 0.000GB/s | 0.0GB/s | ✅ |
| mempool_mt_gain_pct | 75882.090% | 20.0% | ✅ |
| mempool_single_overhead_pct | 0.000% | 5.0% | ✅ |
| ops_per_sec_1kb | 19588.000 ops/s | 17629.2 ops/s | ✅ |
| qos_priority_gain_pct | 558.567% | 22.0% | ✅ |
| rdma_bw_util_pct | 0.149% | 0.134341875% | ✅ |
| simulation_speedup | 3.505x | 1.0x | ✅ |
| warm_read_gbps | 0.000GB/s | 0.0GB/s | ✅ |
| warm_write_gbps | 0.000GB/s | 0.0GB/s | ✅ |
