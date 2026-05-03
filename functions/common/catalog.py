from __future__ import annotations

from copy import deepcopy


MODULE_NAMES = {
    "storage": "多级异构的高效能存储模块",
    "rdma": "RDMA 分布式仿真计算模块",
    "mempool": "一致性总线内存池化仿真计算模块",
}


_SPECS = [
    {
        "module": "storage",
        "fn_id": "FN-1",
        "source_no": 1,
        "name": "仿真引擎异构存储统一访问接口",
        "description": "验证 DRAM、NVMe、HDD 等已配置层级由统一数据面接口暴露和查询。",
        "implementation": [
            "native_rdma/data_plane/storage/tier_engine.cpp",
            "native_rdma/data_plane/storage/io_scheduler.cpp",
            "RPC_TIER_STATS",
        ],
        "criterion": "RPC_TIER_STATS 返回 ok=true，并包含 dram、nvme、hdd 层级计数字段。",
        "scope": [
            "验证统一层级状态接口可用。",
            "不统计读写吞吐或层级带宽，性能归入 performances/PF-6。",
        ],
        "prerequisites": ["数据面 UDS 在线。"],
        "check": "storage_fn1",
    },
    {
        "module": "storage",
        "fn_id": "FN-2",
        "source_no": 2,
        "name": "多层感知、冷热分离与调度",
        "description": "验证对象可经显式 demote 路径进入低层级，并在读取时被重新提升。",
        "implementation": [
            "RPC_KV_PUT",
            "RPC_TIER_DEMOTE",
            "RPC_KV_GET",
            "TierEngine::demote/promote",
        ],
        "criterion": "写入对象后 demote 到 nvme 成功，随后 GET 返回 nvme_promote 命中证据。",
        "scope": [
            "验证手动冷热迁移闭环。",
            "不证明自动访问频率驱动迁移策略收益。",
        ],
        "prerequisites": ["数据面 UDS 在线。"],
        "check": "storage_fn2",
    },
    {
        "module": "storage",
        "fn_id": "FN-3",
        "source_no": 3,
        "name": "多策略预取机制",
        "description": "验证顺序访问可触发 stride 预取预测，并保留 Markov 统计接口。",
        "implementation": [
            "native_rdma/data_plane/storage/prefetcher.cpp",
            "RPC_PREFETCH_STATS",
        ],
        "criterion": "顺序 GET 后 RPC_PREFETCH_STATS 返回 ok=true，predicted 非空且 total_access 增加。",
        "scope": [
            "验证 stride/Markov 统计与预测接口。",
            "不统计预取带来的性能提升。",
        ],
        "prerequisites": ["数据面 UDS 在线。"],
        "check": "storage_fn3",
    },
    {
        "module": "storage",
        "fn_id": "FN-4",
        "source_no": 4,
        "name": "可配置压缩与去重",
        "description": "验证压缩统计接口和可压缩对象冷层写入路径，去重代码纳入构建但当前无独立运行时 RPC。",
        "implementation": [
            "native_rdma/data_plane/storage/compress.cpp",
            "native_rdma/data_plane/storage/dedup.cpp",
            "RPC_COMPRESS_STATS",
            "RPC_TIER_DEMOTE",
        ],
        "criterion": "可写入 4096 字节对象时，demote 到 hdd 后压缩对象数或 saved_bytes 增加。",
        "scope": [
            "验证 ZSTD/LZ4 压缩统计可观测。",
            "记录 dedup.cpp 构建接入事实；当前不伪造去重 RPC 结果。",
        ],
        "prerequisites": ["数据面 UDS 在线。", "SLAB_SLOT_SIZE 至少可容纳 4096 字节对象。"],
        "check": "storage_fn4",
    },
    {
        "module": "storage",
        "fn_id": "FN-5",
        "source_no": 5,
        "name": "IO 调度与优先级管理",
        "description": "验证前台和后台 I/O 调度器初始化，具备高低优先级路径。",
        "implementation": [
            "native_rdma/data_plane/storage/io_scheduler.cpp",
            "native_rdma/logs/dp_<role>.log",
        ],
        "criterion": "当前数据面日志包含 IoScheduler init fg=... bg=... 初始化证据。",
        "scope": [
            "验证前台/后台队列初始化。",
            "不验证优先级吞吐提升比例。",
        ],
        "prerequisites": ["数据面 UDS 在线。", "native_rdma/logs/dp_<role>.log 可读。"],
        "check": "storage_fn5",
    },
    {
        "module": "storage",
        "fn_id": "FN-6",
        "source_no": 6,
        "name": "仿真数据运行中采集",
        "description": "验证仿真运行期间对象属性和交互事件能够进入 SimCapture WAL。",
        "implementation": [
            "native_rdma/data_plane/sim/sim_engine.cpp",
            "native_rdma/data_plane/sim/sim_capture.cpp",
            "RPC_SIM_RUN",
            "RPC_SIM_CAPTURE_STATS",
        ],
        "criterion": "RPC_SIM_RUN 成功后 captured_events、pushed_events、flushed_events 均大于 0。",
        "scope": [
            "验证运行中采集链路和 WAL flush 计数。",
            "不统计仿真加速比性能指标。",
        ],
        "prerequisites": ["数据面 UDS 在线。"],
        "check": "storage_fn6",
    },
    {
        "module": "rdma",
        "fn_id": "FN-1",
        "source_no": 1,
        "name": "RDMA 与 TCP/IP 统一通信层",
        "description": "验证 RDMA QP 初始化和 TCP fallback/OOB 通道初始化证据。",
        "implementation": [
            "native_rdma/data_plane/rdma/rdma_core.cpp",
            "native_rdma/data_plane/rdma/tcp_fallback.cpp",
            "native_rdma/data_plane/rdma/oob.cpp",
        ],
        "criterion": "数据面日志包含 created ... QPs，并包含 TcpFallback listen 或 connected。",
        "scope": [
            "验证 RDMA 与 TCP 控制通道的共同初始化。",
            "不单独压测通信延迟或带宽。",
        ],
        "prerequisites": ["数据面 UDS 在线。", "native_rdma/logs/dp_<role>.log 可读。"],
        "check": "rdma_fn1",
    },
    {
        "module": "rdma",
        "fn_id": "FN-2",
        "source_no": 2,
        "name": "聚合数据传输",
        "description": "验证 BatchAggregator 初始化，并通过批量 PUT RPC 走小对象聚合路径。",
        "implementation": [
            "native_rdma/data_plane/batch/batch_aggregator.cpp",
            "RPC_KV_PUT_BATCH",
        ],
        "criterion": "RPC_KV_PUT_BATCH 返回 ok=true，ok_n 与提交条数一致。",
        "scope": [
            "验证聚合传输功能路径可用。",
            "不统计批处理吞吐或延迟阈值。",
        ],
        "prerequisites": ["数据面 UDS 在线。"],
        "check": "rdma_fn2",
    },
    {
        "module": "rdma",
        "fn_id": "FN-3",
        "source_no": 3,
        "name": "流量优先级机制",
        "description": "验证 QoS 调度器初始化，且高低优先级 PUT 路径均可提交。",
        "implementation": [
            "native_rdma/data_plane/qos/qos_sched.cpp",
            "RPC_KV_PUT_HI",
            "RPC_KV_PUT_LO",
        ],
        "criterion": "日志包含 QosSched ready，RPC_KV_PUT_HI 与 RPC_KV_PUT_LO 均成功。",
        "scope": [
            "验证高低优先级路径可用。",
            "不验证 22% 效率提升，性能归入 performances/PF-3。",
        ],
        "prerequisites": ["数据面 UDS 在线。", "native_rdma/logs/dp_<role>.log 可读。"],
        "check": "rdma_fn3",
    },
    {
        "module": "rdma",
        "fn_id": "FN-4",
        "source_no": 4,
        "name": "CPU 与 GPU 高速直通访问",
        "description": "当前硬件环境未建立 GPU Direct RDMA 验证前提，按需求文档暂时豁免。",
        "implementation": [
            "待补 GPU、CUDA、GPU Direct RDMA 或项目定义的等效直通路径。",
        ],
        "criterion": "当前脚本直接生成 WAIVED，并说明完整验证前提。",
        "scope": [
            "只记录硬件/环境豁免。",
            "不把普通 CPU 内存路径等同为 GPU Direct 验收。",
        ],
        "prerequisites": ["无；当前按 WAIVED 输出。"],
        "check": "rdma_fn4",
    },
    {
        "module": "rdma",
        "fn_id": "FN-5",
        "source_no": 5,
        "name": "分布式节点路由转发与负载均衡",
        "description": "验证 key 到 primary/replica 的一致性哈希路由查询和批量分布。",
        "implementation": [
            "native_rdma/data_plane/router/object_router.cpp",
            "RPC_ROUTE_QUERY",
        ],
        "criterion": "批量 RPC_ROUTE_QUERY 均 ok，primary 非空，并观察到至少两个 primary 分布桶。",
        "scope": [
            "验证路由和分布计数；replica 为空时记录为当前路由策略细节。",
            "不验证跨交换机或多级转发性能。",
        ],
        "prerequisites": ["数据面 UDS 在线。"],
        "check": "rdma_fn5",
    },
    {
        "module": "mempool",
        "fn_id": "FN-1",
        "source_no": 1,
        "name": "RDMA 语义远程内存访问与零拷贝",
        "description": "验证 PUT 走数据面远程写路径，并返回复制时延和路由证据。",
        "implementation": [
            "RPC_KV_PUT",
            "RdmaCore::post_write",
            "SlabPool",
        ],
        "criterion": "peer 在线时 RPC_KV_PUT 返回 ok=true、degraded=false，并包含 repl_ns。",
        "scope": [
            "验证可观测的 RDMA WRITE 复制路径。",
            "零拷贝以用户态 slab 偏移、rkey 和 repl_ns 作为当前证据。",
        ],
        "prerequisites": ["数据面 UDS 在线。", "默认 REQUIRE_PEER=1 时要求 peer_alive=true。"],
        "check": "mempool_fn1",
    },
    {
        "module": "mempool",
        "fn_id": "FN-2",
        "source_no": 2,
        "name": "分布式内存池 API",
        "description": "验证封装后的 UDS PUT/GET API 可以完成对象写入读取闭环。",
        "implementation": [
            "RPC_KV_PUT",
            "RPC_KV_GET",
            "PoolRegistry",
        ],
        "criterion": "写入对象后读取到同一内容，RPC 响应均 ok=true。",
        "scope": [
            "验证数据面 UDS API 闭环。",
            "不只验证 Flask 参数解析。",
        ],
        "prerequisites": ["数据面 UDS 在线。"],
        "check": "mempool_fn2",
    },
    {
        "module": "mempool",
        "fn_id": "FN-3",
        "source_no": 3,
        "name": "内存池统一命名机制",
        "description": "验证 peer slab base、rkey、QP 数等命名与交换信息存在。",
        "implementation": [
            "PoolRegistry",
            "RPC_CLUSTER_STATUS",
            "OOB handshake",
        ],
        "criterion": "RPC_CLUSTER_STATUS 返回 peer_slab_base、peer_slab_rkey、peer_num_qp 且值有效。",
        "scope": [
            "验证共享内存区域命名和 RDMA 元数据交换。",
            "peer 未在线时按 SKIP 处理。",
        ],
        "prerequisites": ["数据面 UDS 在线。", "默认 REQUIRE_PEER=1 时要求 peer_alive=true。"],
        "check": "mempool_fn3",
    },
    {
        "module": "mempool",
        "fn_id": "FN-4",
        "source_no": 4,
        "name": "跨节点内存自适应分配与热数据迁移",
        "description": "验证当前实现中可观测的 TierEngine 热/冷迁移和读取提升路径。",
        "implementation": [
            "TierEngine",
            "RPC_TIER_DEMOTE",
            "RPC_KV_GET",
        ],
        "criterion": "对象 demote 后 GET 触发 nvme_promote，日志包含 TierEngine init。",
        "scope": [
            "验证当前可观测的热数据迁移闭环。",
            "明确该口径不等同于完整跨节点远端内存自适应放置。",
        ],
        "prerequisites": ["数据面 UDS 在线。"],
        "check": "mempool_fn4",
    },
    {
        "module": "mempool",
        "fn_id": "FN-5",
        "source_no": 5,
        "name": "任务级与用户级内存隔离",
        "description": "验证租户 ACL 拒绝、授权、撤销后的写入行为闭环。",
        "implementation": [
            "native_rdma/data_plane/mempool/isolation.cpp",
            "RPC_ISO_ALLOW",
            "RPC_ISO_DENY",
            "RPC_KV_PUT",
        ],
        "criterion": "临时 tenant 完成拒绝、允许、拒绝三段式闭环。",
        "scope": [
            "验证任务级/用户级 ACL 生效。",
            "使用临时 tenant id，避免污染默认租户。",
        ],
        "prerequisites": ["数据面 UDS 在线。"],
        "check": "mempool_fn5",
    },
    {
        "module": "mempool",
        "fn_id": "FN-6",
        "source_no": 6,
        "name": "内存池高可靠机制",
        "description": "默认验证 peer 状态和降级计数字段；显式开启后可做主动 peer 故障演练。",
        "implementation": [
            "RPC_CLUSTER_STATUS",
            "degraded_puts",
            "peer_alive",
            "可选 PEER_SSH/PEER_DP_PATH 主动演练",
        ],
        "criterion": "默认非破坏性检查 peer_alive、degraded_puts、degraded_bytes 字段存在。",
        "scope": [
            "默认不 kill peer。",
            "ALLOW_DESTRUCTIVE=1 且提供 peer 参数时才主动演练故障降级。",
        ],
        "prerequisites": ["数据面 UDS 在线。"],
        "check": "mempool_fn6",
    },
]


for _spec in _SPECS:
    _spec["module_name"] = MODULE_NAMES[_spec["module"]]
    _spec["source"] = (
        f"docs/功能要求.md / {_spec['module_name']} / 第 {_spec['source_no']} 条"
    )


SPEC_ORDER = [(item["module"], item["fn_id"]) for item in _SPECS]


def all_specs() -> list[dict[str, object]]:
    return [deepcopy(item) for item in _SPECS]


def get_spec(module: str, fn_id: str) -> dict[str, object]:
    for item in _SPECS:
        if item["module"] == module and item["fn_id"] == fn_id:
            return deepcopy(item)
    raise KeyError(f"unknown function spec: {module}/{fn_id}")
