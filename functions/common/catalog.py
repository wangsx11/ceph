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
            "RPC_KV_PUT",
            "RPC_TIER_DEMOTE",
            "RPC_KV_GET",
        ],
        "criterion": "RPC_TIER_STATS 返回 ok=true 且包含 dram、nvme、hdd 字段；探针对象可分别 demote 到 nvme/hdd，并通过同一 GET 接口读回原始内容。",
        "scope": [
            "验证统一层级状态接口可用。",
            "验证 DRAM 写入、NVMe/HDD demote 和读回提升闭环。",
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
        "description": "验证对象可经显式 demote 路径进入低层级，并验证后台热度调度能按访问频率区分热/冷对象。",
        "implementation": [
            "RPC_KV_PUT",
            "RPC_TIER_DEMOTE",
            "RPC_TIER_STATS",
            "RPC_KV_GET",
            "TierEngine::demote/promote",
            "TierEngine::calc_heat_score",
            "main.cpp tier migrator thread",
        ],
        "criterion": "手动探针 demote 到 nvme 后 GET 返回 nvme_promote；自动探针中冷对象在等待窗口后下沉到 nvme，热对象持续访问期间不发生下沉。",
        "scope": [
            "验证手动冷热迁移闭环。",
            "验证访问频率驱动的自动冷热分离行为。",
            "不统计迁移性能或吞吐收益。",
        ],
        "prerequisites": ["数据面 UDS 在线。"],
        "check": "storage_fn2",
    },
    {
        "module": "storage",
        "fn_id": "FN-3",
        "source_no": 3,
        "name": "多策略预取机制",
        "description": "验证 stride 和 Markov 两种策略可预测后续 key，并能把低层对象提前加载到 DRAM。",
        "implementation": [
            "native_rdma/data_plane/storage/prefetcher.cpp",
            "RPC_PREFETCH_STATS",
            "RPC_KV_GET",
            "RPC_TIER_DEMOTE",
            "TierEngine::promote",
        ],
        "criterion": "stride 和 Markov 场景均返回预期 predicted key；预测对象预先 demote 到 nvme 后，应被 GET 触发的预取逻辑提前 promote，后续 GET 命中 local，并增加 prefetch_loaded/prefetch_hits。",
        "scope": [
            "验证 stride/Markov 预测策略。",
            "验证预测对象的实际预取加载和后续命中。",
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
        "description": "验证可压缩对象冷层写入路径，并验证重复对象进入 HDD 冷层时触发运行时去重。",
        "implementation": [
            "native_rdma/data_plane/storage/compress.cpp",
            "native_rdma/data_plane/storage/dedup.cpp",
            "RPC_COMPRESS_STATS",
            "RPC_DEDUP_STATS",
            "RPC_TIER_DEMOTE",
            "TierEngine::dedup_stats",
        ],
        "criterion": "两个相同 4096 字节对象 demote 到 hdd 后，压缩 objects/saved_bytes 增加，去重 duplicate_objects/saved_bytes 增加，且两个对象均可从 HDD 读回。",
        "scope": [
            "验证 ZSTD/LZ4 压缩统计可观测。",
            "验证运行时 SHA-256 指纹去重统计可观测。",
            "不统计压缩/去重带来的性能收益。",
        ],
        "prerequisites": ["数据面 UDS 在线。", "SLAB_SLOT_SIZE 至少可容纳 4096 字节对象。"],
        "check": "storage_fn4",
    },
    {
        "module": "storage",
        "fn_id": "FN-5",
        "source_no": 5,
        "name": "IO 调度与优先级管理",
        "description": "验证前台和后台 I/O 调度器初始化，并验证 NVMe/HDD 路径分别产生 FG/BG I/O 计数。",
        "implementation": [
            "native_rdma/data_plane/storage/io_scheduler.cpp",
            "native_rdma/logs/dp_<role>.log",
            "RPC_IO_STATS",
            "RPC_TIER_DEMOTE",
            "RPC_KV_GET",
        ],
        "criterion": "数据面日志包含 IoScheduler init fg=... bg=...；NVMe demote/get 使 FG read/write 计数增加，HDD demote/get 使 BG read/write 计数增加。",
        "scope": [
            "验证前台/后台队列初始化。",
            "验证前台/后台 I/O 路径真实可观测。",
            "不统计优先级吞吐提升比例。",
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
        "criterion": "RPC_SIM_RUN 成功后 captured/pushed/flushed 计数和字节数均大于 0，dropped_events=0；RPC_SIM_CAPTURE_STATS 暴露 ObjectAttr/InteractionEvent 计数和 wal_path；脚本解析 WAL 文件确认 type=1 与 type=2 均存在且无截断。",
        "scope": [
            "验证运行中采集链路、WAL flush 计数和二进制 WAL 内容。",
            "验证对象属性与交互事件两类数据流均进入采集文件。",
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
        "description": "验证 RDMA QP 初始化、TCP fallback/OOB 通道初始化、当前 peer 在线证据，以及传统 TCP/IP 数据传输闭环。",
        "implementation": [
            "native_rdma/data_plane/rdma/rdma_core.cpp",
            "native_rdma/data_plane/rdma/tcp_fallback.cpp",
            "native_rdma/data_plane/rdma/oob.cpp",
        ],
        "criterion": "最近一次数据面启动日志包含 created ... QPs、TcpFallback 和 OOB exchanged；REQUIRE_PEER=1 时 RPC_CLUSTER_STATUS 必须 peer_alive=true 且 peer 元数据有效；数据面必须以 NR_TRANSPORT=tcp、NR_ASYNC_REPL=0 启动，普通 RPC_KV_PUT 必须通过 TCP 复制到 peer，RPC_TCP_GET_PEER 必须读回同一内容；脚本采集 RDMA 与 TCP 复制时延样本并写入 raw/summary。",
        "scope": [
            "验证 RDMA 与 TCP/OOB 控制通道的共同初始化。",
            "REQUIRE_PEER=1 时验证当前双节点通信层仍在线，不使用历史日志制造 PASS。",
            "验证传统 TCP/IP 数据通道可承载普通 PUT 复制和 peer 读取闭环。",
            "展示 RDMA 与 TCP/IP 的同步复制时延 avg/p50/p95 样本；该数值只作为功能测试中的微基准展示，不替代正式性能测试。",
        ],
        "prerequisites": ["数据面 UDS 在线。", "native_rdma/logs/dp_<role>.log 可读。", "完整验收要求 xfusion4 peer 在线。"],
        "check": "rdma_fn1",
    },
    {
        "module": "rdma",
        "fn_id": "FN-2",
        "source_no": 2,
        "name": "聚合数据传输",
        "description": "验证 BatchAggregator 初始化，并通过批量 PUT RPC 走小对象 RDMA 批量传输与 peer 读回闭环。",
        "implementation": [
            "native_rdma/data_plane/batch/batch_aggregator.cpp",
            "native_rdma/data_plane/main.cpp 的 RPC_KV_PUT_BATCH",
            "RPC_TCP_GET_PEER",
        ],
        "criterion": "最近启动日志包含 BatchAggregator/RDMA QP/OOB 证据；REQUIRE_PEER=1 时 peer_alive=true；NR_ASYNC_REPL=0 下 RPC_KV_PUT_BATCH 返回 ok=true、ok_n=replicated_n=提交条数、degraded_n=0、repl_failed_n=0，并可通过 RPC_TCP_GET_PEER 从 peer 逐项读回同值。",
        "scope": [
            "验证批量小对象 RDMA 传输功能路径可用。",
            "验证 peer 端读回闭环，不使用 peer 离线本地批量写结果冒充 RDMA 聚合传输。",
            "不统计批处理吞吐、延迟阈值或 doorbell 聚合性能收益。",
        ],
        "prerequisites": ["数据面 UDS 在线。", "完整验收要求 xfusion4 peer 在线。", "建议以 NR_TRANSPORT=rdma NR_ASYNC_REPL=0 启动。"],
        "check": "rdma_fn2",
    },
    {
        "module": "rdma",
        "fn_id": "FN-3",
        "source_no": 3,
        "name": "流量优先级机制",
        "description": "验证 QoS 调度器初始化，且高低优先级 PUT 分别使用 RDMA 高/低优先级 QP 分组并可从 peer 读回。",
        "implementation": [
            "native_rdma/data_plane/qos/qos_sched.cpp",
            "native_rdma/data_plane/main.cpp 的 QoS PUT 响应字段",
            "RPC_KV_PUT_HI",
            "RPC_KV_PUT_LO",
            "RPC_TCP_GET_PEER",
        ],
        "criterion": "最近启动日志包含 QosSched/RDMA QP/OOB 证据；REQUIRE_PEER=1 时 peer_alive=true；NR_ASYNC_REPL=0 下 RPC_KV_PUT_HI/LO 均返回 transport=rdma、degraded=false，且 qos.qp_idx 分别落在高/低优先级 QP 分组；随后 RPC_TCP_GET_PEER 从 peer 读回同值。",
        "scope": [
            "验证高低优先级路径可用且映射到不同 RDMA QP 分组。",
            "验证 peer 端读回闭环，不使用 peer 离线本地降级写结果冒充 RDMA QoS 数据面。",
            "不验证 22% 效率提升，性能归入 performances/PF-3。",
        ],
        "prerequisites": ["数据面 UDS 在线。", "native_rdma/logs/dp_<role>.log 可读。", "完整验收要求 xfusion4 peer 在线。"],
        "check": "rdma_fn3",
    },
    {
        "module": "rdma",
        "fn_id": "FN-4",
        "source_no": 4,
        "name": "CPU 与 GPU 高速直通访问",
        "description": "验证 xfusion3 通过 RDMA WRITE/READ 直接访问 xfusion4 CUDA GPU MR，并由 xfusion4 CUDA kernel 校验显存内容。",
        "implementation": [
            "native_rdma/data_plane/gpu/gpu_direct.cu",
            "native_rdma/data_plane/rdma/oob.cpp 的 GPU MR 元数据交换",
            "native_rdma/data_plane/main.cpp 的 RPC_GDR_STATUS/WRITE/READBACK/VALIDATE",
        ],
        "criterion": "RPC_CLUSTER_STATUS peer_alive=true 且 transport=rdma；RPC_GDR_STATUS 证明 peer GPU MR base/rkey/len 有效；A 调 RPC_GDR_WRITE 写入 B GPU MR；B 调 RPC_GDR_VALIDATE 由 CUDA kernel 校验内容正确；A 调 RPC_GDR_READBACK 读回并校验一致。",
        "scope": [
            "验证 xfusion4 NVIDIA GPU、CUDA、nvidia_peermem 与 RDMA 设备可用。",
            "验证 GPU buffer 由 cudaMalloc 分配并注册为 RDMA MR。",
            "验证 CPU 只提交 RDMA WR，payload 经 RNIC 进入 GPU 显存；不把普通 CPU slab、TCP 或 cudaMemcpy 全量 payload 等同为 GPU Direct 验收。",
        ],
        "prerequisites": ["数据面 UDS 在线。", "完整验收要求 xfusion4 peer 在线。", "xfusion4 已加载 nvidia-peermem。", "以 NR_GDR_ENABLE=1 启动双节点。"],
        "check": "rdma_fn4",
    },
    {
        "module": "rdma",
        "fn_id": "FN-5",
        "source_no": 5,
        "name": "分布式节点路由转发与负载均衡",
        "description": "验证 key 到 primary/replica 的一致性哈希路由查询、批量分布和 remote-primary routed PUT 转发闭环。",
        "implementation": [
            "native_rdma/data_plane/router/object_router.cpp",
            "RPC_ROUTE_QUERY",
            "RPC_ROUTE_PUT",
            "RPC_TCP_GET_PEER",
        ],
        "criterion": "批量 RPC_ROUTE_QUERY 均 ok，primary 非空，并观察到至少两个 primary 分布桶；REQUIRE_PEER=1 时 peer_alive=true；脚本同时找到本地/远端 primary key，本地 RPC_ROUTE_PUT 不转发且本地 GET 可读回，远端 primary RPC_ROUTE_PUT 发生 route_forwarded=true、forward_transport=rdma，并可通过 RPC_TCP_GET_PEER 从 peer 读回同值。",
        "scope": [
            "验证路由查询和分布计数；replica 为空时记录为当前路由策略细节。",
            "验证 remote-primary key 的 RDMA 跨节点转发闭环，不只做路由表展示。",
            "不验证跨交换机或多级转发性能；RPC_TCP_GET_PEER 仅作为 peer 内容读回校验通道。",
        ],
        "prerequisites": ["数据面 UDS 在线。", "完整验收要求 xfusion4 peer 在线。", "RDMA transport 在线。", "TCP data channel 在线用于 peer 读回校验。"],
        "check": "rdma_fn5",
    },
    {
        "module": "mempool",
        "fn_id": "FN-1",
        "source_no": 1,
        "name": "RDMA 语义远程内存访问与零拷贝",
        "description": "验证 PUT 强制走数据面 RDMA WRITE 远程写路径，并从 peer 读回同一对象。",
        "implementation": [
            "RPC_KV_PUT_RDMA",
            "RPC_TCP_GET_PEER",
            "RPC_CLUSTER_STATUS",
            "RdmaCore::post_write",
            "SlabPool",
        ],
        "criterion": "peer 在线时 RPC_KV_PUT_RDMA 返回 ok=true、transport=rdma、degraded=false、repl_ns>0；peer slab base/len/rkey/QP 元数据有效；PUT offset/size 落在 peer slab 范围内；RPC_TCP_GET_PEER 能从 peer 读回同一 value。",
        "scope": [
            "验证可观测的 RDMA WRITE 复制路径，不允许 TCP transport 或本地 degraded 写入冒充。",
            "验证 peer 端远程内存实际包含写入对象。",
            "零拷贝以用户态注册 slab、peer rkey、远端 offset 范围和 RDMA 完成时延作为当前证据。",
        ],
        "prerequisites": ["数据面 UDS 在线。", "默认 REQUIRE_PEER=1 时要求 peer_alive=true。", "TCP data channel 在线以执行 peer 读回校验。"],
        "check": "mempool_fn1",
    },
    {
        "module": "mempool",
        "fn_id": "FN-2",
        "source_no": 2,
        "name": "分布式内存池 API",
        "description": "验证封装后的 UDS PUT/GET API 可以完成本地读取和 peer 端副本读回闭环。",
        "implementation": [
            "RPC_KV_PUT",
            "RPC_KV_GET",
            "RPC_TCP_GET_PEER",
            "RPC_CLUSTER_STATUS",
            "PoolRegistry",
        ],
        "criterion": "peer 在线时，RPC_CLUSTER_STATUS 暴露本地和 peer slab/MR 元数据；普通 RPC_KV_PUT 返回 ok=true、transport=rdma、degraded=false，offset/size 落在本地和 peer slab 范围内；RPC_KV_GET 和 RPC_TCP_GET_PEER 均能读回同一内容。",
        "scope": [
            "验证数据面 UDS API 闭环，不只验证 Flask 参数解析。",
            "验证普通 PUT API 屏蔽底层 RDMA 复制细节，但实际落到 C++ 数据面和 peer 副本。",
            "不统计 API 吞吐或延迟性能。",
        ],
        "prerequisites": ["数据面 UDS 在线。", "默认 REQUIRE_PEER=1 时要求 peer_alive=true。", "TCP data channel 在线以执行 peer 读回校验。"],
        "check": "mempool_fn2",
    },
    {
        "module": "mempool",
        "fn_id": "FN-3",
        "source_no": 3,
        "name": "内存池统一命名机制",
        "description": "验证本地与远端共享内存区域在 PoolRegistry 中使用同一逻辑 pool 名称，并与 OOB 交换的 slab/rkey/QP 元数据一致。",
        "implementation": [
            "PoolRegistry",
            "RPC_CLUSTER_STATUS",
            "RPC_MEMPOOL_POOLS",
            "OOB handshake",
        ],
        "criterion": "RPC_CLUSTER_STATUS 返回本地和 peer slab base/len/lkey/rkey/QP 字段且值有效；RPC_MEMPOOL_POOLS 返回本地和远端同名 default/slab1k；registry 中的 base/len/lkey/rkey 与 cluster/OOB 元数据一致。",
        "scope": [
            "验证共享内存区域统一命名、PoolRegistry 本地/远端登记和 RDMA 元数据交换。",
            "peer 未在线时按 SKIP 处理，不用历史 OOB 字段制造 PASS。",
            "不验证多 pool 枚举或动态 pool 创建。",
        ],
        "prerequisites": ["数据面 UDS 在线。", "默认 REQUIRE_PEER=1 时要求 peer_alive=true。"],
        "check": "mempool_fn3",
    },
    {
        "module": "mempool",
        "fn_id": "FN-4",
        "source_no": 4,
        "name": "跨节点内存自适应分配与热数据迁移",
        "description": "验证冷对象可自适应放置到远端 RDMA slab，并在连续访问成为热点后通过 RDMA READ 迁回本地 slab。",
        "implementation": [
            "RPC_MEMPOOL_ADAPT_PUT",
            "RPC_MEMPOOL_ADAPT_GET",
            "RPC_MEMPOOL_ADAPT_STATS",
            "RPC_KV_GET",
            "RdmaCore::post_write",
            "RdmaCore::post_read",
            "TierEngine",
        ],
        "criterion": "RPC_MEMPOOL_ADAPT_PUT 将冷对象 RDMA WRITE 到 peer slab；首次访问保持 remote RDMA READ；达到热点阈值后 RDMA READ 迁回本地 slab；随后普通 RPC_KV_GET 本地命中。",
        "scope": [
            "验证 RDMA 本地/远端内存自适应放置和热点数据本地化迁移。",
            "peer 未在线时按 SKIP 处理，不用存储层 NVMe/HDD demote 冒充跨节点内存迁移。",
            "不统计迁移收益或吞吐性能。",
        ],
        "prerequisites": ["数据面 UDS 在线。", "默认 REQUIRE_PEER=1 时要求 peer_alive=true。", "TCP data channel 在线以执行 peer 读回校验。"],
        "check": "mempool_fn4",
    },
    {
        "module": "mempool",
        "fn_id": "FN-5",
        "source_no": 5,
        "name": "任务级与用户级内存隔离",
        "description": "验证租户 ACL 拒绝、授权、撤销闭环，并验证两个已授权 tenant 使用同一逻辑 key 时互不串读。",
        "implementation": [
            "native_rdma/data_plane/mempool/isolation.cpp",
            "main.cpp tenant_storage_key",
            "RPC_ISO_ALLOW",
            "RPC_ISO_DENY",
            "RPC_ISO_LIST",
            "RPC_KV_PUT",
            "RPC_KV_GET",
        ],
        "criterion": "两个临时 tenant 未授权写入失败；授权后分别用同一逻辑 key 写入不同 value 并读回各自 value；撤销后对应 tenant 再次访问失败；RPC_ISO_LIST 反映 ACL 状态变化。",
        "scope": [
            "验证任务级/用户级 ACL 生效和非默认 tenant 内部 key 命名空间隔离。",
            "使用临时 tenant id，避免污染默认租户。",
            "不验证 Linux 进程 UID/GID 或硬件 PD/MR 级隔离。",
        ],
        "prerequisites": ["数据面 UDS 在线。"],
        "check": "mempool_fn5",
    },
    {
        "module": "mempool",
        "fn_id": "FN-6",
        "source_no": 6,
        "name": "内存池高可靠机制",
        "description": "验证 heartbeat peer 状态、peer 故障期间本地可用降级写入、降级计数递增，以及恢复后的 RDMA 非降级复制。",
        "implementation": [
            "RPC_CLUSTER_STATUS",
            "Heartbeat::peer_alive",
            "degraded_puts",
            "degraded_bytes",
            "RPC_KV_PUT",
            "RPC_KV_GET",
            "RPC_TCP_GET_PEER",
            "peer_alive",
            "ALLOW_DESTRUCTIVE=1 主动 peer 故障演练",
        ],
        "criterion": "主动演练时先要求 peer_alive=true；kill peer 后必须观测 peer_alive=false，RPC_KV_PUT 返回 ok=true/degraded=true，本地 RPC_KV_GET 读回同值，degraded_puts/degraded_bytes 递增；恢复命令执行后 peer_alive=true，后续 PUT 走 RDMA 非降级复制并可从 peer 读回。",
        "scope": [
            "默认不 kill peer，仅做非破坏性字段检查并标记部分完成。",
            "完整验收需 ALLOW_DESTRUCTIVE=1、PEER_SSH、PEER_DP_PATH 和 FN6_RECOVERY_CMD。",
            "验证 peer 失联期间本节点继续提供本地 PUT/GET 可用性；不宣称无需重启即可自动重新 OOB/QP 握手。",
        ],
        "prerequisites": ["数据面 UDS 在线。", "完整验收要求 xfusion3/xfusion4 双节点 RDMA 在线。"],
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
