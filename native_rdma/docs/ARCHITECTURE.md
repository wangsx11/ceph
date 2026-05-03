# 架构细节（ARCHITECTURE.md）

> 本文档是 `docs/自研方案.md` 的代码落地视图。占位符含义见根 [README.md](../README.md)。

当前里程碑：**W1 - 骨架搭建完成**，以下模块已建立 C++ 接口与基础实现：

| 模块 | 目录 | 状态 |
|---|---|---|
| RdmaCore | `data_plane/rdma/` | ✅ 设备打开 / QP & CQ 创建 / MR 注册 / post 接口 |
| Mempool  | `data_plane/mempool/` | ✅ SlabPool (HugePage+MR)；Arena 为 bump 占位 |
| Router   | `data_plane/router/` | ✅ 一致性 hash + primary/replica 路由 |
| QoS      | `data_plane/qos/` | ✅ 高低优先级 QP + 令牌桶 |
| Batch    | `data_plane/batch/` | ✅ MPSC 队列 + WR 链表聚合 |
| Storage  | `data_plane/storage/` | ⚙️ tier/compress/dedup 可用；prefetcher/snapshot/io_uring 骨架 |
| Replication | `data_plane/replication/` | ⚙️ 同步复制 + 心跳骨架 |
| Sim      | `data_plane/sim/` | 🟡 骨架 |
| API      | `data_plane/api/` | ✅ UDS server + 共享内存指标 |

下一里程碑（W2）：打通跨节点握手 + 1KB put/get 全链路，具体里程碑参见 `docs/自研方案.md` 第 10 章。
