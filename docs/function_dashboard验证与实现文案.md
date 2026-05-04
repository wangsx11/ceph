# function_dashboard 验证与实现文案

本文档只用于前端“验证与实现”窗口展示。内容按功能验收视角组织，聚焦真实数据面路径、关键状态和可复查结果证据。

## storage/FN-1 仿真引擎异构存储统一访问接口

### 验证目标
功能要求：提供仿真引擎异构存储功能，兼容多种存储设备，包括 NVMe、SATA 固态盘、ZNS SSD 等新型存储设备，提供统一访问接口。

- 验证 DRAM、NVMe、HDD 等已配置层级通过同一数据面接口可查询、可写入、可读取。
- 验证对象迁移到不同层级后，仍能通过同一 key 读回原始内容。
- 以层级统计、读命中来源、`summary.md` 和 `raw.json` 作为闭环证据。

### 实现方案
- C++ 数据面由 `TierEngine` 管理热层、温层和冷层，`IoScheduler` 承接不同层级的 I/O 操作。
- Flask 控制面触发 functions 单项入口，入口通过 UDS 直连数据面 RPC。
- 关键路径包括 `RPC_TIER_STATS` 查询层级状态、`RPC_KV_PUT` 写入对象、`RPC_TIER_DEMOTE` 下沉对象、`RPC_KV_GET` 读回对象。
- 前端只展示验收文案与结果材料，结果证据来自功能点目录中的结果摘要和原始结果。

### 测试方案

前置条件：
- C++ 数据面在线，UDS 可访问。
- 热层、温层和冷层路径已按部署配置初始化。
- Flask 控制面可触发功能点执行。

测试方案：
- 调用 `RPC_TIER_STATS`，确认层级统计返回成功且包含可用层级。
- 写入测试对象后分别触发温层、冷层迁移。
- 再次读取对象，检查返回内容一致，并确认命中来源反映层级读回或提升。
- 检查 `summary.md` 和 `raw.json` 中的层级、命中和结果字段。

## storage/FN-2 多层感知、冷热分离与调度

### 验证目标
功能要求：提供多层感知与调度机制，识别数据所属存储层级，并根据访问频率、局部性对存储数据进行冷热分离，以提升访问效率和吞吐量。

- 验证数据面能够识别对象所在层级，并记录冷热迁移后的状态变化。
- 验证冷对象可下沉，热对象可保持在热层或在读取时提升。
- 验证手动迁移和访问热度驱动的调度路径都有可观测结果。

### 实现方案
- `TierEngine` 维护对象热度、层级位置和迁移策略。
- 数据面通过 `RPC_TIER_DEMOTE`、后台迁移线程和 `RPC_KV_GET` 读时提升形成冷热分离闭环。
- 控制面触发 functions 单项入口后，入口经 UDS 调用真实数据面 RPC，并把迁移状态写入结果文件。
- 关键证据来自层级统计、读命中来源和对象读回内容，而不是静态文件检查。

### 测试方案

前置条件：
- C++ 数据面在线，UDS 可访问。
- 层级迁移线程和层级目录已初始化。
- 测试期间对象 key 不与其他验收数据冲突。

测试方案：
- 写入冷对象并触发迁移，检查迁移 RPC 返回成功。
- 读取迁移后的对象，确认内容一致且命中来源体现低层级读回或提升。
- 写入热对象并进行连续访问，确认热对象保持在热层。
- 检查 `summary.md` 和 `raw.json` 中冷热对象、层级变化和最终结果。

## storage/FN-3 多策略预取机制

### 验证目标
功能要求：提供文件访问的多策略预取机制，提升系统在实时仿真、仿真回放、结果分析等多种应用场景下的存储效率。

- 验证顺序、步长或 Markov 等访问模式能够触发预取决策。
- 验证被预测对象能从低层级提前提升到热层。
- 验证预取命中、加载和跳过计数通过数据面统计可复查。

### 实现方案
- C++ 数据面 `Prefetcher` 记录访问序列并生成预测目标。
- `RPC_KV_GET` 在读取路径触发预取，`TierEngine` 执行目标对象提升。
- `RPC_PREFETCH_STATS` 返回访问、加载、命中等计数，functions 入口直连 UDS 采集这些字段。
- 结果摘要展示预取闭环，性能收益不放在本窗口证明。

### 测试方案

前置条件：
- C++ 数据面在线，UDS 可访问。
- 预取器已随数据面初始化。
- 低层级测试对象已可被迁移和读回。

测试方案：
- 准备一组有规律的对象访问序列，并将预测目标放入低层级。
- 通过 UDS 读取对象，触发顺序或 Markov 预取路径。
- 查询 `RPC_PREFETCH_STATS`，检查加载数和命中数发生变化。
- 读取预测目标，确认已回到热层且内容正确。
- 检查 `summary.md` 和 `raw.json` 中的预取统计和命中证据。

## storage/FN-4 可配置压缩与去重

### 验证目标
功能要求：提供可配置的数据压缩与去重机制，降低存储空间和网络传输开销，提升仿真数据存储效率与资源利用率。

- 验证可压缩对象进入冷层时触发压缩统计。
- 验证重复对象进入冷层时触发去重统计。
- 验证压缩或去重后的对象仍能完整读回。

### 实现方案
- C++ 数据面由 `CompressEngine` 和 `DedupIndex` 处理冷层写入前的压缩与重复对象识别。
- `TierEngine` 在对象下沉到 HDD 冷层时接入压缩与去重路径。
- functions 入口通过 UDS 调用 `RPC_COMPRESS_STATS`、`RPC_DEDUP_STATS`、对象写入、迁移和读回 RPC。
- 前端只展示压缩、去重计数和读回结果，不展示内部入口内容。

### 测试方案

前置条件：
- C++ 数据面在线，UDS 可访问。
- 冷层路径可写，压缩和去重模块已初始化。
- 测试对象内容可控，便于形成压缩和重复数据。

测试方案：
- 写入可压缩对象和重复对象，并触发下沉到冷层。
- 查询 `RPC_COMPRESS_STATS`，检查压缩对象数和节省字节数变化。
- 查询 `RPC_DEDUP_STATS`，检查重复对象数和去重节省字段。
- 读取两个对象，确认内容与写入值一致。
- 检查 `summary.md` 和 `raw.json` 中的压缩、去重和读回证据。

## storage/FN-5 IO 调度与优先级管理

### 验证目标
功能要求：提供 IO 调度与优先级管理功能，将仿真过程中的 I/O 操作分为高实时性前台 I/O 和延迟容忍型后台 I/O，保障高优先级 I/O 操作。

- 验证前台 I/O 与后台 I/O 路径都由数据面调度器接管。
- 验证不同层级操作能落到对应的前台或后台计数。
- 验证对象经过调度路径后仍能正确读回。

### 实现方案
- C++ 数据面 `IoScheduler` 初始化前台和后台队列，分层写入与读取会记录对应计数。
- `TierEngine` 在 NVMe、HDD 等层级操作中调用调度器。
- functions 入口通过 UDS 查询 `RPC_IO_STATS`，并执行写入、迁移、读取闭环。
- 本窗口只展示功能闭环和计数字段，不展示性能收益比例。

### 测试方案

前置条件：
- C++ 数据面在线，UDS 可访问。
- I/O 调度器随数据面启动完成。
- 温层和冷层路径可用。

测试方案：
- 查询初始 `RPC_IO_STATS`，记录前台和后台计数。
- 执行温层对象写入、迁移和读取，检查前台计数变化。
- 执行冷层对象写入、迁移和读取，检查后台计数变化。
- 读取对象确认内容一致。
- 检查 `summary.md` 和 `raw.json` 中的计数增量和结果字段。

## storage/FN-6 仿真数据运行中采集

### 验证目标
功能要求：支持仿真数据运行中采集，支撑模块能够在仿真运行过程中及时捕获多类型的数据流，包括对象属性、交互事件等。

- 验证仿真运行期间能产生对象属性和交互事件两类数据。
- 验证采集模块能记录 pushed、flushed、dropped 等关键状态。
- 验证 WAL 内容与数据面采集统计一致。

### 实现方案
- C++ 数据面由 `SimEngine` 产生运行事件，`SimCapture` 负责事件缓冲、flush 和 WAL 写入。
- 控制面触发 functions 单项入口后，入口通过 UDS 调用 `RPC_SIM_RUN` 和 `RPC_SIM_CAPTURE_STATS`。
- 验收会解析 WAL 中的事件头和类型字段，确认 ObjectAttr 与 InteractionEvent 均真实落盘。
- 前端展示采集统计与原始结果，不展示实时日志片段。

### 测试方案

前置条件：
- C++ 数据面在线，UDS 可访问。
- 仿真采集目录可写。
- 采集模块随数据面初始化完成。

测试方案：
- 调用 `RPC_SIM_RUN` 运行短时仿真，产生对象属性和交互事件。
- 调用 `RPC_SIM_CAPTURE_STATS`，检查 captured、pushed、flushed 等字段。
- 解析 WAL，确认事件数量、字节数和事件类型符合预期。
- 检查 dropped 或截断字段，确认采集过程无异常丢失。
- 检查 `summary.md` 和 `raw.json` 中的 RPC 统计和 WAL 解析证据。

## rdma/FN-1 RDMA 与 TCP/IP 统一通信层

### 验证目标
功能要求：提供支持 RDMA 与传统 TCP/IP 的统一通信层，通过独立协议适配器实现协议之间的无冲突切换与运行。

- 验证 RDMA 与 TCP 数据通道都能通过统一控制面触发。
- 验证协议切换后对象复制和 peer 读回仍能完成。
- 验证 `peer_alive`、transport、OOB 状态等关键字段可观测。

### 实现方案
- C++ 数据面初始化 RDMA QP、OOB 元数据交换和 TCP data channel。
- 普通 PUT 按配置选择 RDMA 或 TCP 复制路径，显式 RDMA PUT 可用于对照验证。
- functions 入口直连 UDS 调用 cluster 状态、普通 PUT、RDMA PUT 和 peer 读取 RPC。
- 结果材料保留协议、peer 状态、复制时延和读回一致性证据。

### 测试方案

前置条件：
- 双节点数据面在线，UDS 可访问。
- peer 在线，OOB 元数据交换完成。
- RDMA 设备和 TCP data channel 状态有效。

测试方案：
- 查询 `RPC_CLUSTER_STATUS`，确认 peer、transport、OOB 和 TCP data 状态。
- 通过普通 PUT 走当前配置的数据通道，并检查返回的 transport 和 degraded 字段。
- 通过显式 RDMA PUT 做对照，确认 RDMA 路径可用。
- 从 peer 读取对象，确认复制后的内容一致。
- 检查 `summary.md` 和 `raw.json` 中的协议切换与读回证据。

## rdma/FN-2 聚合数据传输

### 验证目标
功能要求：支持聚合数据传输功能，对小规模数据包或多个并发通信流进行高效聚合。

- 验证批量小对象可通过数据面批量入口一次提交。
- 验证批量写入中的每个对象都返回成功并完成 peer 副本。
- 验证 peer 端能够逐项读回同值，形成聚合传输闭环。

### 实现方案
- C++ 数据面提供批量 PUT RPC，并复用 slab、tier 和 RDMA 复制路径。
- `BatchAggregator` 负责聚合能力初始化，批量 RPC 记录成功数、复制数和降级数。
- functions 入口通过 UDS 调用 `RPC_KV_PUT_BATCH`，随后通过 peer 读取接口校验每个对象。
- 结果展示批量计数和 peer 读回，不展示吞吐性能指标。

### 测试方案

前置条件：
- 双节点数据面在线，UDS 可访问。
- peer 在线，RDMA 传输路径有效。
- TCP peer 校验通道可访问。

测试方案：
- 查询 cluster 状态，确认 peer 在线且传输状态满足验收要求。
- 提交一组小对象到批量 PUT RPC。
- 检查返回的 ok 数、replicated 数、degraded 数和失败数字段。
- 从 peer 逐项读取对象，确认内容全部一致。
- 检查 `summary.md` 和 `raw.json` 中的批量计数和 peer 读回证据。

## rdma/FN-3 流量优先级机制

### 验证目标
功能要求：支持流量优先级机制，根据不同数据流的优先级对网络资源进行调度和分配，保证关键数据优先传输。

- 验证高优先级和低优先级写入能进入不同的调度分组。
- 验证两类优先级写入都走真实 RDMA 数据面并完成 peer 副本。
- 验证响应中的 priority、QP 分组和 peer 读回结果可复查。

### 实现方案
- C++ 数据面 `QosSched` 维护高低优先级 QP 分组。
- 高优先级和低优先级 PUT RPC 在提交 RDMA WRITE 时选择对应 QP。
- functions 入口通过 UDS 调用高低优先级写入，再通过 peer 读取接口校验内容。
- 结果展示 QP 分组和读回闭环，不展示性能提升百分比。

### 测试方案

前置条件：
- 双节点数据面在线，UDS 可访问。
- peer 在线，RDMA QP 初始化完成。
- QoS 调度器随数据面启动完成。

测试方案：
- 查询 cluster 状态，确认 RDMA 和 peer 状态有效。
- 调用高优先级 PUT，检查响应中的 priority 和 QP 编号。
- 调用低优先级 PUT，检查响应中的 priority 和 QP 编号。
- 分别从 peer 读取对象，确认内容一致。
- 检查 `summary.md` 和 `raw.json` 中的 QP 分组、degraded 字段和读回证据。

## rdma/FN-4 CPU 与 GPU 高速直通访问

### 验证目标
功能要求：支持 CPU 与 GPU 之间的高速直通访问功能，使 GPU 直接读写远程内存，避免 CPU 参与数据搬运，降低通信延迟。

- 验证 xfusion4 的 GPU buffer 能注册为 RDMA MR 并通过 OOB 暴露给 peer。
- 验证 xfusion3 能通过 RDMA WRITE 直接写入 xfusion4 的 GPU MR。
- 验证 GPU 侧校验和 RDMA READBACK 校验都能确认内容一致。

### 实现方案
- C++/CUDA 数据面在 xfusion4 使用 `cudaMalloc` 分配 GPU buffer，并注册为 RDMA MR。
- OOB 交换 GPU MR 的 base、len、rkey 等元数据，xfusion3 使用这些信息提交 RDMA WRITE。
- xfusion4 通过 CUDA kernel 校验 GPU 显存内容，xfusion3 可通过 RDMA READBACK 做回读校验。
- functions 入口通过 UDS 调用 `RPC_GDR_STATUS`、`RPC_GDR_WRITE`、`RPC_GDR_VALIDATE` 和 `RPC_GDR_READBACK`。

### 测试方案

前置条件：
- 双节点数据面在线，UDS 可访问。
- xfusion4 具备可用 NVIDIA GPU、CUDA peer memory 支持和 `mlx5_0` RDMA 设备。
- OOB 已交换 peer GPU MR 元数据。

测试方案：
- 查询 `RPC_GDR_STATUS`，确认 peer GPU MR 的 base、len、rkey 有效。
- 从 xfusion3 调用 `RPC_GDR_WRITE` 写入指定 pattern，检查 RDMA 返回成功且未降级。
- 在 xfusion4 调用 GPU 校验 RPC，检查 CUDA kernel 返回 mismatches 为 0。
- 从 xfusion3 调用 RDMA READBACK，检查读回 pattern、checksum 和 mismatches。
- 检查 `summary.md` 和 `raw.json` 中的 GPU MR、写入、GPU 校验和回读证据。

## rdma/FN-5 分布式节点路由转发与负载均衡

### 验证目标
功能要求：支持分布式节点之间数据传输的路由转发、负载均衡。

- 验证 key 到 primary 节点的路由查询可用。
- 验证批量 key 的 primary 分布能覆盖双节点。
- 验证本地 primary 和远端 primary 写入都能完成读回闭环。

### 实现方案
- C++ 数据面 `ObjectRouter` 使用一致性哈希计算对象 primary 节点。
- `RPC_ROUTE_QUERY` 返回路由决策，`RPC_ROUTE_PUT` 按 primary 执行本地写入或远端转发。
- 远端 primary 当前通过 TCP data channel 完成转发写入，随后通过 peer 读取接口校验内容。
- functions 入口通过 UDS 调用路由查询、路由写入和 peer 读取 RPC。

### 测试方案

前置条件：
- 双节点数据面在线，UDS 可访问。
- peer 在线，路由表和 TCP data channel 状态有效。
- 本地与远端节点地址在 cluster 状态中可识别。

测试方案：
- 对一组 key 调用 `RPC_ROUTE_QUERY`，统计 primary 节点分布。
- 选择本地 primary key 执行 routed PUT，检查未转发并本地读回。
- 选择远端 primary key 执行 routed PUT，检查转发状态和转发通道字段。
- 从 peer 读取远端 primary 对象，确认内容一致。
- 检查 `summary.md` 和 `raw.json` 中的分布、转发和读回证据。

## mempool/FN-1 RDMA 语义远程内存访问与零拷贝

### 验证目标
功能要求：支持 RDMA 语义特性直接远程访问内存，消除数据在内核和用户空间之间不必要的 CPU 拷贝，提升数据传输的效率。

- 验证对象 PUT 走 RDMA WRITE 远程内存访问路径。
- 验证 peer slab 的 base、len、rkey、QP 等元数据有效。
- 验证远端 offset 范围正确，并能从 peer 读回同值。

### 实现方案
- C++ 数据面使用用户态注册 slab 作为本地和远端内存池。
- OOB 交换 peer slab 的 base、len、rkey、QPN 等 RDMA 元数据。
- `RPC_KV_PUT_RDMA` 强制走 RDMA WRITE，响应返回 transport、degraded、repl_ns、offset 等字段。
- functions 入口通过 UDS 调用 RDMA PUT 和 peer 读取 RPC，证明远端内存写入闭环。

### 测试方案

前置条件：
- 双节点数据面在线，UDS 可访问。
- peer 在线，RDMA transport 与 OOB 元数据有效。
- TCP peer 校验通道可访问。

测试方案：
- 查询 `RPC_CLUSTER_STATUS`，确认 peer slab 元数据完整。
- 调用 `RPC_KV_PUT_RDMA` 写入对象，检查 transport 为 RDMA 且未降级。
- 检查 offset 和 size 落在 peer slab 范围内。
- 从 peer 读取对象，确认内容与写入值一致。
- 检查 `summary.md` 和 `raw.json` 中的 peer slab、RDMA 写入和读回证据。

## mempool/FN-2 分布式内存池 API

### 验证目标
功能要求：提供分布式内存池基本功能，提供封装好的 API 接口，支持用户空间直接访问远程内存区域，屏蔽底层网络细节，提升开发效率与系统可移植性。

- 验证普通 PUT/GET API 能完成本地读写闭环。
- 验证调用方无需指定 RDMA 细节，数据面仍能完成 peer 副本。
- 验证本地读回和 peer 读回内容一致。

### 实现方案
- C++ 数据面以 slab pool 和 `PoolRegistry` 提供封装后的键值对象 API。
- 普通 `RPC_KV_PUT` 根据 cluster 状态选择 RDMA 复制路径，并返回 transport、degraded、offset 等字段。
- `RPC_KV_GET` 完成本地 API 读回，peer 读取接口用于校验远端副本。
- functions 入口通过 UDS 调用上述 RPC，结果材料记录 API 闭环和副本一致性。

### 测试方案

前置条件：
- 双节点数据面在线，UDS 可访问。
- peer 在线，RDMA 或校验通道状态有效。
- 默认内存池已在两端注册。

测试方案：
- 查询 cluster 状态，确认本地和 peer slab 元数据有效。
- 调用普通 `RPC_KV_PUT` 写入对象，检查返回成功、未降级和 offset 字段。
- 调用 `RPC_KV_GET` 从本地读回，确认内容一致。
- 从 peer 读取对象，确认副本内容一致。
- 检查 `summary.md` 和 `raw.json` 中的 API 返回、slab 元数据和读回证据。

## mempool/FN-3 内存池统一命名机制

### 验证目标
功能要求：提供内存池统一命名机制，用于标识不同仿真节点间共享的内存区域。

- 验证本地和远端共享 slab 使用同一 pool 命名。
- 验证 `PoolRegistry` 中的本地、远端元数据与 cluster/OOB 字段一致。
- 验证 base、len、lkey、rkey 等关键字段有效。

### 实现方案
- C++ 数据面 `PoolRegistry` 登记默认 pool 和 slab 名称。
- OOB handshake 完成后，将远端 slab 元数据登记到同一命名空间。
- `RPC_MEMPOOL_POOLS` 返回本地与远端 pool 列表，`RPC_CLUSTER_STATUS` 返回 OOB 交换后的 slab 字段。
- functions 入口通过 UDS 对比 registry 与 cluster 字段，确认统一命名和元数据一致。

### 测试方案

前置条件：
- 双节点数据面在线，UDS 可访问。
- peer 在线，OOB 元数据交换完成。
- 默认共享内存池已注册。

测试方案：
- 调用 `RPC_CLUSTER_STATUS`，确认 peer slab base、len、rkey 等字段有效。
- 调用 `RPC_MEMPOOL_POOLS`，确认 local 和 remote 均存在同名 pool。
- 对比本地 registry 与 cluster 本地 slab 元数据。
- 对比远端 registry 与 OOB peer slab 元数据。
- 检查 `summary.md` 和 `raw.json` 中的命名、元数据和一致性证据。

## mempool/FN-4 跨节点内存自适应分配与热数据迁移

### 验证目标
功能要求：支持跨节点内存自适应分配与热数据迁移，能够支持 RDMA 本地内存与远端内存的自适应分配，动态识别热点数据并将仿真数据存放于本地内存。

- 验证冷对象可优先放置到远端 RDMA slab。
- 验证远端对象可通过 RDMA READ 访问。
- 验证连续访问达到热点阈值后，对象迁移回本地 slab。

### 实现方案
- C++ 数据面提供 `RPC_MEMPOOL_ADAPT_PUT`、`RPC_MEMPOOL_ADAPT_GET` 和 `RPC_MEMPOOL_ADAPT_STATS`。
- 冷对象写入时通过 RDMA WRITE 放置到 peer slab，并记录 remote offset。
- 热点读取路径通过 RDMA READ 拉取远端内容，达到阈值后写入本地 slab 形成本地化。
- functions 入口通过 UDS 调用自适应 RPC，并用本地读回和 peer 读回校验迁移前后内容。

### 测试方案

前置条件：
- 双节点数据面在线，UDS 可访问。
- peer 在线，RDMA WRITE 和 RDMA READ 路径有效。
- TCP peer 校验通道可访问。

测试方案：
- 调用自适应 PUT，检查 placement 为 remote 且未降级。
- 从 peer 读取对象，确认远端放置内容正确。
- 连续调用自适应 GET，检查前几次为远端读取。
- 达到热点阈值后检查返回的迁移状态和本地 offset。
- 检查 `summary.md` 和 `raw.json` 中的 placement、RDMA read、迁移计数和本地命中证据。

## mempool/FN-5 任务级与用户级内存隔离

### 验证目标
功能要求：提供任务级与用户级内存隔离机制，对不同仿真任务使用独立的内存空间，支持多用户之间的内存访问隔离。

- 验证未授权 tenant 访问被拒绝。
- 验证授权 tenant 可写入和读回自己的对象。
- 验证不同 tenant 使用同一逻辑 key 时互不串读。
- 验证撤销授权后访问再次被拒绝。

### 实现方案
- C++ 数据面 `IsolationManager` 维护 tenant 到 pool 的 ACL。
- 数据面内部 key 带 tenant 命名空间前缀，避免不同任务或用户的同名 key 冲突。
- `RPC_ISO_ALLOW`、`RPC_ISO_DENY` 和 `RPC_ISO_LIST` 管理授权状态，tenant 版 `RPC_KV_PUT/GET` 执行数据面读写。
- functions 入口通过 UDS 完成拒绝、授权、读写、撤销的闭环。

### 测试方案

前置条件：
- C++ 数据面在线，UDS 可访问。
- 隔离管理器已随数据面初始化。
- 测试 tenant id 独立，避免影响默认租户。

测试方案：
- 使用两个临时 tenant 访问同一逻辑 key，确认初始未授权写入失败。
- 授权 tenant A 后写入并读回，确认 tenant B 仍不可访问 A 的数据。
- 授权 tenant B 后写入同一逻辑 key，确认 A/B 读回各自 value。
- 撤销授权后再次访问，确认对应 tenant 被拒绝。
- 检查 `summary.md` 和 `raw.json` 中的 ACL 状态、拒绝/允许结果和命名空间隔离证据。

## mempool/FN-6 内存池高可靠机制

### 验证目标
功能要求：内存池提供高可靠机制，保证在部分节点故障的情况下，系统继续可用。

- 验证 peer 在线状态和降级计数字段可观测。
- 验证 peer 故障期间本节点仍能完成本地 degraded 写入和读取。
- 验证 peer 恢复后可重新完成非降级复制和 peer 读回。

### 实现方案
- C++ 数据面 heartbeat 维护 peer 存活状态，并在 cluster 状态中暴露 `peer_alive`。
- 写入路径在 peer 不可用时走本地 degraded 分支，并更新 `degraded_puts`、`degraded_bytes`。
- peer 恢复后，普通 PUT 回到 RDMA 非降级复制路径。
- functions 入口通过 UDS 检查状态、写入、读取和恢复后的复制闭环；主动故障演练只在明确允许时执行。

### 测试方案

前置条件：
- 双节点数据面在线，UDS 可访问。
- peer 初始在线，heartbeat、RDMA 和 OOB 状态有效。
- 测试环境允许执行受控故障演练，并具备恢复 peer 的条件。

测试方案：
- 查询 cluster 状态，记录 peer 在线状态和降级计数。
- 触发受控 peer 故障后，确认本节点观测到 `peer_alive=false`。
- 故障期间执行 PUT/GET，检查写入为 degraded 且本地读回成功。
- 检查 degraded 计数和字节数增加。
- peer 恢复后再次执行 PUT，并从 peer 读回对象，确认恢复为非降级复制。
- 检查 `summary.md` 和 `raw.json` 中的故障、降级、恢复和读回证据。
