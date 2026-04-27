wangshouxin@xfusion3:~/ceph-web$ bash tests/functional/rdma_distributed/run.sh
========== test_01_protocol_switch.py ==========
[INFO] cluster ms_type = unknown
[INFO] mon session did not report rdma explicitly; relying on ms_type setting
[ OK ] functional 2.1 PASS — unified protocol surface
========== test_02_batch_aggregation.py ==========
[ OK ] single 100-object batch: 29.94 ms <= 100 ms
[ OK ] single 1000-object batch: 128.19 ms <= 200 ms
[ OK ] functional 2.2 PASS — batch aggregation
========== test_03_qos_priority.py ==========
[INFO] throughput H=21727 ops/s  L=3437 ops/s  gain=532.2%
[ OK ] high-priority gain: 532.19% >= 22.0%
[ OK ] functional 2.3 PASS — QoS priority
========== test_04_gpu_direct.py ==========
[INFO] PEER_HOST env not set; running server side only – please launch `ib_write_bw` on the peer manually, or set PEER_HOST and rerun
[INFO] SKIP – peer host required for loopback BW measurement
========== test_05_routing_lb.py ==========
[INFO] CRUSH host weights: {'xfusion3': 1.7465972900390625, 'xfusion4': 1.81939697265625, 'xfusion5': 1.81939697265625}
[INFO] host weights: [1.7465972900390625, 1.81939697265625, 1.81939697265625];  hosts active=3;  worst deviation=2.7%
[ OK ] active OSD hosts: 3.00 >= 2
[ OK ] max deviation: 2.70% <= 30%
[ OK ] functional 2.5 PASS — routing & load balancing
[DONE] rdma_distributed all PASS
