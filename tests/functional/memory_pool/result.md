wangshouxin@xfusion3:~/ceph-web$ bash tests/functional/memory_pool/run.sh
========== test_01_zero_copy_rdma.py ==========
[INFO] PEER_HOST not set; functional test requires a peer – SKIP
========== test_02_mempool_api.py ==========
[CephManager] connected, fsid=4243f7e2-0340-11f1-babb-15cb9f8efe98
[CephManager] using pool testbench namespace mempool_pool
[ OK ] functional 3.2 PASS — mempool api round-trip
========== test_03_namespace.py ==========
[INFO] other namespace correctly denied
[ OK ] functional 3.3 PASS — unified naming & namespaces
========== test_04_adaptive_alloc.py ==========
[CephManager] connected, fsid=4243f7e2-0340-11f1-babb-15cb9f8efe98
[CephManager] using pool testbench namespace mempool_pool
[INFO] initial placement: {'name': 'test_adaptive', 'local': 50, 'remote': 200, 'handles': 250, 'migrations': 0}
[ OK ] hot hint local count: 50.00 >= 50
[ OK ] cold hint remote count: 200.00 >= 150
[INFO] after rebalance: {'name': 'test_adaptive', 'local': 80, 'remote': 170, 'handles': 250, 'migrations': 30}
[ OK ] migrations triggered: 30.00 >= 10
[ OK ] functional 3.4 PASS — adaptive local/remote allocation
========== test_05_isolation.py ==========
[ OK ] functional 3.5 PASS — task/user isolation
========== test_06_ha_failover.py ==========
[INFO] marking osd.0 out …
[INFO] degraded reads OK
[ OK ] functional 3.6 PASS — HA across OSD failure
[DONE] memory_pool all PASS
