# Functions Summary (2026-05-04T14:53:58+0800)

- Total: 17
- PASS: 15
- FAIL: 0
- SKIP: 2
- WAIVED: 0
- Result: FAIL
- Run All Log: /home/wangshouxin/native-rdma-web/functions/logs/summary_refresh_20260504_145358.log

## 模块汇总

| Module | Total | PASS | FAIL | SKIP | WAIVED |
|---|---:|---:|---:|---:|---:|
| storage | 6 | 6 | 0 | 0 | 0 |
| rdma | 5 | 5 | 0 | 0 | 0 |
| mempool | 6 | 4 | 0 | 2 | 0 |

## 功能点结果

| Module | FN | Function | Result | Completion | Summary |
|---|---|---|---|---|---|
| storage | FN-1 | 仿真引擎异构存储统一访问接口 | PASS | 完成 | `/home/wangshouxin/native-rdma-web/functions/storage/FN-1/summary.md` |
| storage | FN-2 | 多层感知、冷热分离与调度 | PASS | 完成 | `/home/wangshouxin/native-rdma-web/functions/storage/FN-2/summary.md` |
| storage | FN-3 | 多策略预取机制 | PASS | 完成 | `/home/wangshouxin/native-rdma-web/functions/storage/FN-3/summary.md` |
| storage | FN-4 | 可配置压缩与去重 | PASS | 完成 | `/home/wangshouxin/native-rdma-web/functions/storage/FN-4/summary.md` |
| storage | FN-5 | IO 调度与优先级管理 | PASS | 完成 | `/home/wangshouxin/native-rdma-web/functions/storage/FN-5/summary.md` |
| storage | FN-6 | 仿真数据运行中采集 | PASS | 完成 | `/home/wangshouxin/native-rdma-web/functions/storage/FN-6/summary.md` |
| rdma | FN-1 | RDMA 与 TCP/IP 统一通信层 | PASS | 完成 | `/home/wangshouxin/native-rdma-web/functions/rdma/FN-1/summary.md` |
| rdma | FN-2 | 聚合数据传输 | PASS | 完成 | `/home/wangshouxin/native-rdma-web/functions/rdma/FN-2/summary.md` |
| rdma | FN-3 | 流量优先级机制 | PASS | 完成 | `/home/wangshouxin/native-rdma-web/functions/rdma/FN-3/summary.md` |
| rdma | FN-4 | CPU 与 GPU 高速直通访问 | PASS | 完成 | `/home/wangshouxin/native-rdma-web/functions/rdma/FN-4/summary.md` |
| rdma | FN-5 | 分布式节点路由转发与负载均衡 | PASS | 完成 | `/home/wangshouxin/native-rdma-web/functions/rdma/FN-5/summary.md` |
| mempool | FN-1 | RDMA 语义远程内存访问与零拷贝 | SKIP | 未完成 | `/home/wangshouxin/native-rdma-web/functions/mempool/FN-1/summary.md` |
| mempool | FN-2 | 分布式内存池 API | PASS | 完成 | `/home/wangshouxin/native-rdma-web/functions/mempool/FN-2/summary.md` |
| mempool | FN-3 | 内存池统一命名机制 | SKIP | 未完成 | `/home/wangshouxin/native-rdma-web/functions/mempool/FN-3/summary.md` |
| mempool | FN-4 | 跨节点内存自适应分配与热数据迁移 | PASS | 部分完成 | `/home/wangshouxin/native-rdma-web/functions/mempool/FN-4/summary.md` |
| mempool | FN-5 | 任务级与用户级内存隔离 | PASS | 完成 | `/home/wangshouxin/native-rdma-web/functions/mempool/FN-5/summary.md` |
| mempool | FN-6 | 内存池高可靠机制 | PASS | 部分完成 | `/home/wangshouxin/native-rdma-web/functions/mempool/FN-6/summary.md` |

## 未完成项

- mempool/FN-1 SKIP: REQUIRE_PEER=1 且 peer_alive=false，跳过需要双节点的验证
- mempool/FN-3 SKIP: REQUIRE_PEER=1 且 peer_alive=false，跳过需要双节点的验证
