wangshouxin@xfusion3:~/ceph-web$ bash tests/functional/storage_heterogeneous/run.sh
========== test_01_heterogeneous_access.py ==========
[ OK ] pool test_hetero_ssd: 1MB put/get verified
[ OK ] heterogeneous classes verified: 1.00 class >= 1 class
[ OK ] functional 1.1 PASS — unified access over heterogeneous devices
========== test_02_tier_hotcold.py ==========
[CephManager] 已连接到Ceph集群, fsid=4243f7e2-0340-11f1-babb-15cb9f8efe98
[M6] 清理完成: warm=0, cold=0, hot=0
[INFO] seeding 60 objects into warm_pool
[INFO] driving access pattern
[INFO] tier_state={'hot': 20, 'warm': 60, 'cold': 20}
[ OK ] hot-tier promoted count: 20.00 >= 15
[ OK ] cold-tier demoted count: 20.00 >= 15
[ OK ] functional 1.2 PASS — tier awareness & hot/cold separation
========== test_03_prefetch.py ==========
[ OK ] prefetch-hit [sequential]: 99.50% >= 70%
[ OK ] prefetch-hit [random]: 81.00% >= 40%
[ OK ] prefetch-hit [replay]: 99.50% >= 70%
[ OK ] functional 1.3 PASS — multi-strategy prefetch
========== test_04_compression_dedup.py ==========
[INFO] no-compress stored = 6400.0 KB
[INFO] zstd stored      = 2133.3 KB
[ OK ] compression ratio: 3.00x >= 1.5x
[ OK ] functional 1.4 PASS — compression & dedup effective
========== test_05_io_priority.py ==========
[INFO] baseline: P99 = 2.63 ms
[INFO] triggering deep-scrub on all PGs …
[INFO] under-scrub: P99 = 2.86 ms
[ OK ] P99 under background pressure: 0.00s <= 0.00289784s
[ OK ] functional 1.5 PASS — high-priority foreground IO protected
========== test_06_live_capture.py ==========
[INFO] baseline read P50 = 109.2 μs
[INFO] read-while-write latency P50 = 128.5 μs  samples=1000
[ OK ] live-capture P50: 128.50 μs <= 500.0 μs
[ OK ] functional 1.6 PASS — live simulation data capture
[DONE] storage_heterogeneous all PASS
