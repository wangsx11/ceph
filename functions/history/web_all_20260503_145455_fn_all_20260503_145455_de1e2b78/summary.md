# Functions Summary (2026-05-03T14:54:56+0800)

- Total: 17
- PASS: 0
- FAIL: 0
- SKIP: 16
- WAIVED: 1
- Result: PASS
- Run All Log: /home/wangshouxin/ceph-web/functions/logs/run_all_20260503_145455.log

## 模块汇总

| Module | Total | PASS | FAIL | SKIP | WAIVED |
|---|---:|---:|---:|---:|---:|
| storage | 6 | 0 | 0 | 6 | 0 |
| rdma | 5 | 0 | 0 | 4 | 1 |
| mempool | 6 | 0 | 0 | 6 | 0 |

## 功能点结果

| Module | FN | Function | Result | Completion | Summary |
|---|---|---|---|---|---|
| storage | FN-1 | 仿真引擎异构存储统一访问接口 | SKIP | 未完成 | `/home/wangshouxin/ceph-web/functions/storage/FN-1/summary.md` |
| storage | FN-2 | 多层感知、冷热分离与调度 | SKIP | 未完成 | `/home/wangshouxin/ceph-web/functions/storage/FN-2/summary.md` |
| storage | FN-3 | 多策略预取机制 | SKIP | 未完成 | `/home/wangshouxin/ceph-web/functions/storage/FN-3/summary.md` |
| storage | FN-4 | 可配置压缩与去重 | SKIP | 未完成 | `/home/wangshouxin/ceph-web/functions/storage/FN-4/summary.md` |
| storage | FN-5 | IO 调度与优先级管理 | SKIP | 未完成 | `/home/wangshouxin/ceph-web/functions/storage/FN-5/summary.md` |
| storage | FN-6 | 仿真数据运行中采集 | SKIP | 未完成 | `/home/wangshouxin/ceph-web/functions/storage/FN-6/summary.md` |
| rdma | FN-1 | RDMA 与 TCP/IP 统一通信层 | SKIP | 未完成 | `/home/wangshouxin/ceph-web/functions/rdma/FN-1/summary.md` |
| rdma | FN-2 | 聚合数据传输 | SKIP | 未完成 | `/home/wangshouxin/ceph-web/functions/rdma/FN-2/summary.md` |
| rdma | FN-3 | 流量优先级机制 | SKIP | 未完成 | `/home/wangshouxin/ceph-web/functions/rdma/FN-3/summary.md` |
| rdma | FN-4 | CPU 与 GPU 高速直通访问 | WAIVED | 硬件/环境豁免 | `/home/wangshouxin/ceph-web/functions/rdma/FN-4/summary.md` |
| rdma | FN-5 | 分布式节点路由转发与负载均衡 | SKIP | 未完成 | `/home/wangshouxin/ceph-web/functions/rdma/FN-5/summary.md` |
| mempool | FN-1 | RDMA 语义远程内存访问与零拷贝 | SKIP | 未完成 | `/home/wangshouxin/ceph-web/functions/mempool/FN-1/summary.md` |
| mempool | FN-2 | 分布式内存池 API | SKIP | 未完成 | `/home/wangshouxin/ceph-web/functions/mempool/FN-2/summary.md` |
| mempool | FN-3 | 内存池统一命名机制 | SKIP | 未完成 | `/home/wangshouxin/ceph-web/functions/mempool/FN-3/summary.md` |
| mempool | FN-4 | 跨节点内存自适应分配与热数据迁移 | SKIP | 未完成 | `/home/wangshouxin/ceph-web/functions/mempool/FN-4/summary.md` |
| mempool | FN-5 | 任务级与用户级内存隔离 | SKIP | 未完成 | `/home/wangshouxin/ceph-web/functions/mempool/FN-5/summary.md` |
| mempool | FN-6 | 内存池高可靠机制 | SKIP | 未完成 | `/home/wangshouxin/ceph-web/functions/mempool/FN-6/summary.md` |

## 未完成项

- storage/FN-1 SKIP: UDS RPC RPC_TIER_STATS 调用失败: [Errno 1] Operation not permitted
- storage/FN-2 SKIP: UDS RPC RPC_KV_PUT 调用失败: [Errno 1] Operation not permitted
- storage/FN-3 SKIP: UDS RPC RPC_KV_PUT 调用失败: [Errno 1] Operation not permitted
- storage/FN-4 SKIP: UDS RPC RPC_COMPRESS_STATS 调用失败: [Errno 1] Operation not permitted
- storage/FN-5 SKIP: UDS RPC RPC_CLUSTER_STATUS 调用失败: [Errno 1] Operation not permitted
- storage/FN-6 SKIP: UDS RPC RPC_SIM_CAPTURE_RESET 调用失败: [Errno 1] Operation not permitted
- rdma/FN-1 SKIP: UDS RPC RPC_CLUSTER_STATUS 调用失败: [Errno 1] Operation not permitted
- rdma/FN-2 SKIP: UDS RPC RPC_KV_PUT_BATCH 调用失败: [Errno 1] Operation not permitted
- rdma/FN-3 SKIP: UDS RPC RPC_CLUSTER_STATUS 调用失败: [Errno 1] Operation not permitted
- rdma/FN-5 SKIP: UDS RPC RPC_ROUTE_QUERY 调用失败: [Errno 1] Operation not permitted
- mempool/FN-1 SKIP: UDS RPC RPC_CLUSTER_STATUS 调用失败: [Errno 1] Operation not permitted
- mempool/FN-2 SKIP: UDS RPC RPC_KV_PUT 调用失败: [Errno 1] Operation not permitted
- mempool/FN-3 SKIP: UDS RPC RPC_CLUSTER_STATUS 调用失败: [Errno 1] Operation not permitted
- mempool/FN-4 SKIP: UDS RPC RPC_CLUSTER_STATUS 调用失败: [Errno 1] Operation not permitted
- mempool/FN-5 SKIP: UDS RPC RPC_ISO_DENY 调用失败: [Errno 1] Operation not permitted
- mempool/FN-6 SKIP: UDS RPC RPC_CLUSTER_STATUS 调用失败: [Errno 1] Operation not permitted
