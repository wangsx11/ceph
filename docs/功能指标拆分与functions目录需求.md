# 功能指标拆分与 functions 目录需求说明

## 1. 背景

当前功能要求集中记录在 `docs/功能要求.md` 中，现有可参考的功能验证逻辑主要位于 `native_rdma/scripts/acceptance_all.sh`、`native_rdma/scripts/demo_walkthrough.sh` 和 `native_rdma/scripts/health_check.sh`。

其中 `native_rdma/tests/run_all_functional.sh` 目前只是占位入口，尚未落地独立的 `tests/functional/` 测试目录。后续希望参照 `performances/` 的交付形态，将每个功能点拆成独立的功能验证交付单元，便于逐项阅读、执行、产出日志、统计完成情况和验收。

本文只定义 `functions/` 功能测试目录的目标形态和实现约束，不内嵌具体脚本代码。后续实现会话应按本文直接创建 `functions/` 目录、根入口、各功能点目录和脚本。

## 2. 目标目录

在仓库根目录创建 `functions/`，该目录与 `native_rdma/`、`performances/` 同级：

```text
ceph-web/
├── native_rdma/
├── performances/
├── functions/
│   ├── run_all.sh
│   ├── run_all.py
│   ├── summary.md
│   ├── common/
│   ├── storage/
│   │   ├── FN-1/
│   │   ├── FN-2/
│   │   ├── FN-3/
│   │   ├── FN-4/
│   │   ├── FN-5/
│   │   └── FN-6/
│   ├── rdma/
│   │   ├── FN-1/
│   │   ├── FN-2/
│   │   ├── FN-3/
│   │   ├── FN-4/
│   │   └── FN-5/
│   └── mempool/
│       ├── FN-1/
│       ├── FN-2/
│       ├── FN-3/
│       ├── FN-4/
│       ├── FN-5/
│       └── FN-6/
└── docs/
```

三个模块目录统一使用简洁英文名，映射关系如下：

| 目录名 | 对应功能模块 |
|---|---|
| `storage/` | 多级异构的高效能存储模块 |
| `rdma/` | RDMA 分布式仿真计算模块 |
| `mempool/` | 一致性总线内存池化仿真计算模块 |

`FN-N` 编号在每个模块目录内独立从 `FN-1` 开始递增，不作为全局唯一编号。功能点的唯一定位方式为：

```text
functions/<module>/FN-N/
```

## 3. 单个 FN 目录文件要求

每个 `functions/<module>/FN-N/` 目录至少包含以下文件和子目录：

```text
functions/<module>/FN-N/
├── logs/
├── FN-N.md
├── run.sh
├── run.py
└── summary.md
```

### 3.1 `logs/`

`logs/` 用于保存该功能点每次执行的过程日志和原始证据，建议后续实现时按时间戳命名：

```text
logs/
├── run_20260503_153000.log
├── run_20260503_153000.json
└── run_20260503_153000.md
```

日志目录至少应保存：

- 脚本标准输出和标准错误。
- 关键 RPC、HTTP、UDS 或命令调用的原始响应。
- 判断 PASS、FAIL、SKIP、WAIVED 的证据。
- 环境检查信息，例如数据面 UDS、控制面 HTTP、构建产物、peer 状态。

### 3.2 `FN-N.md`

该文件描述单个功能点的测试要求、实现说明和验证方案，必须包含：

- 功能点名称。
- 来源要求，例如来自 `docs/功能要求.md` 的哪个模块第几条。
- 功能点说明。
- 当前实现位置，包括 C++ 数据面、Python 控制面、前端或脚本入口。
- 完成判据，明确什么情况算“已完成”。
- 测试口径，明确验证哪些行为、字段、日志或状态，不验证哪些性能指标。
- 前置条件，包括是否要求双节点、RDMA 连接、Flask 控制面、特定硬件或特定环境变量。
- 交互流程，包括启动环境、设置参数、执行脚本、查看结果。
- 脚本入口，固定指向本目录下的 `run.sh` 和 `run.py`。
- 输出文件规则，固定说明本次运行结果写入当前 `functions/<module>/FN-N/` 目录和其 `logs/` 子目录。

建议结构参考：

```markdown
# FN-N 功能点名称测试说明

## 功能点

## 来源要求

## 实现位置

## 完成判据

## 测试方案

## 交互

## 实现

### 当前验证口径

### 脚本入口

## 命令
```

### 3.3 `run.sh`

`run.sh` 是该功能点的 Bash 入口，职责是：

- 定位仓库根目录、模块目录和当前 `FN-N` 目录。
- 设置默认环境变量。
- 创建 `logs/` 目录。
- 确认本次运行的输出文件位置。
- 调用 `run.py`。
- 将退出码传递给调用方。

后续实现时，`run.sh` 应尽量只做环境准备和入口封装，核心测试逻辑放在 `run.py`。

### 3.4 `run.py`

`run.py` 是该功能点的核心测试代码，职责是：

- 读取环境变量或命令行参数。
- 检查依赖条件，例如数据面 UDS、控制面 HTTP、目标二进制、peer 状态、硬件前提。
- 执行功能验证步骤。
- 采集原始输出。
- 根据完成判据计算 `PASS`、`FAIL`、`SKIP` 或 `WAIVED`。
- 将本次执行日志写入 `logs/`。
- 生成或更新当前目录下的 `summary.md`。
- 如该功能点需要保留机器可读原始数据，可在 `logs/` 或当前目录下生成 `raw.json`、`raw.csv` 等辅助文件。

### 3.5 `summary.md`

`summary.md` 是该功能点最近一次执行结果的汇总文件：

- `functions/<module>/FN-N/summary.md`：作为该功能点最近一次执行结果文档。
- 每次执行 `run.py` 后必须更新。
- 只展示最近一次执行结果，不保留历史统计。
- 不要求按时间戳创建独立结果目录，每次运行的过程日志和原始证据统一放入 `logs/`。

`summary.md` 至少包含：

- 功能点名称。
- 来源要求。
- 最近一次运行时间。
- 最近一次运行结果：`PASS`、`FAIL`、`SKIP` 或 `WAIVED`。
- 完成情况：`完成`、`部分完成`、`未完成`、`硬件/环境豁免`。
- 关键证据。
- 日志文件路径。
- 统计口径说明。

示例结构：

```markdown
# FN-N Summary

- Module: 模块名称
- Function: 功能点名称
- Source: docs/功能要求.md / 模块 X / 第 N 条
- Last Run: 2026-05-03T15:30:00+08:00
- Result: PASS
- Completion: 完成
- Evidence: xxx
- Log: logs/run_20260503_153000.log

口径：
- 验证 xxx 行为。
- 不统计性能指标。
```

## 4. 结果输出要求

每个功能点的说明、执行脚本、日志和最近一次最终结果都放在同一个 `FN-N` 目录下，建议格式：

```text
functions/<module>/FN-N/
├── logs/
│   ├── run_<timestamp>.log
│   └── run_<timestamp>.json
├── FN-N.md
├── run.sh
├── run.py
├── summary.md
├── raw.json      # 可选，保存最近一次机器可读结果
└── raw.csv       # 可选，保存最近一次表格型结果
```

`summary.md` 是必须文件，只用于记录该功能点最近一次执行结果。`logs/` 是必须目录，用于保存每次执行的过程证据。`raw.json`、`raw.csv` 只作为辅助文件存在：

- 如果该功能点需要保留机器可读最近一次结果，可以生成 `raw.json`。
- 如果该功能点存在表格型输出，可以生成 `raw.csv`。
- 如果不需要原始辅助文件，应在 `summary.md` 中保留人工可读汇总，并在 `logs/` 中保留过程日志。

脚本结果状态建议统一为：

| 状态 | 含义 | 退出码建议 |
|---|---|---:|
| `PASS` | 功能验证通过，完成判据满足 | 0 |
| `FAIL` | 功能验证执行成功但判据不满足 | 1 |
| `SKIP` | 前置依赖缺失，无法执行本项验证 | 2 |
| `WAIVED` | 功能点受硬件或环境约束，按文档豁免 | 0 |

## 5. FN 编号与功能映射

以下映射来自当前 `docs/功能要求.md`，并参考现有 `native_rdma/scripts/acceptance_all.sh` 的功能验收意图。

### 5.1 多级异构的高效能存储模块

| 模块内编号 | 来源编号 | 功能点 | 当前实现或参考入口 | 输出目录 |
|---|---:|---|---|---|
| `FN-1` | 1 | 仿真引擎异构存储统一访问接口 | `RPC_TIER_STATS`、`TierEngine`、`IoScheduler` | `functions/storage/FN-1/` |
| `FN-2` | 2 | 多层感知、冷热分离与调度 | `RPC_TIER_DEMOTE`、`TierEngine` | `functions/storage/FN-2/` |
| `FN-3` | 3 | 多策略预取机制 | `RPC_PREFETCH_STATS`、`Prefetcher` | `functions/storage/FN-3/` |
| `FN-4` | 4 | 可配置压缩与去重 | `RPC_COMPRESS_STATS`、`CompressEngine`、`DedupIndex` | `functions/storage/FN-4/` |
| `FN-5` | 5 | IO 调度与优先级管理 | `IoScheduler` 日志与前后台队列 | `functions/storage/FN-5/` |
| `FN-6` | 6 | 仿真数据运行中采集 | `RPC_SIM_RUN`、`RPC_SIM_CAPTURE_STATS`、`SimCapture` | `functions/storage/FN-6/` |

### 5.2 RDMA 分布式仿真计算模块

| 模块内编号 | 来源编号 | 功能点 | 当前实现或参考入口 | 输出目录 |
|---|---:|---|---|---|
| `FN-1` | 1 | RDMA 与 TCP/IP 统一通信层 | RDMA QP 初始化日志、`TcpFallback` | `functions/rdma/FN-1/` |
| `FN-2` | 2 | 聚合数据传输 | `BatchAggregator`、批处理 RPC 或日志 | `functions/rdma/FN-2/` |
| `FN-3` | 3 | 流量优先级机制 | `QosSched`、高低优先级队列或日志 | `functions/rdma/FN-3/` |
| `FN-4` | 4 | CPU 与 GPU 高速直通访问 | `RPC_GDR_STATUS`、`RPC_GDR_WRITE`、`RPC_GDR_VALIDATE`、`RPC_GDR_READBACK` | `functions/rdma/FN-4/` |
| `FN-5` | 5 | 分布式节点路由转发与负载均衡 | `RPC_ROUTE_QUERY`、一致性哈希路由 | `functions/rdma/FN-5/` |

### 5.3 一致性总线内存池化仿真计算模块

| 模块内编号 | 来源编号 | 功能点 | 当前实现或参考入口 | 输出目录 |
|---|---:|---|---|---|
| `FN-1` | 1 | RDMA 语义远程内存访问与零拷贝 | `RPC_KV_PUT`、复制延迟字段、RDMA 传输路径 | `functions/mempool/FN-1/` |
| `FN-2` | 2 | 分布式内存池 API | `RPC_KV_PUT`、`RPC_KV_GET`、`PoolRegistry` | `functions/mempool/FN-2/` |
| `FN-3` | 3 | 内存池统一命名机制 | `RPC_CLUSTER_STATUS` 中 peer slab base/rkey 等字段 | `functions/mempool/FN-3/` |
| `FN-4` | 4 | 跨节点内存自适应分配与热数据迁移 | `TierEngine`、迁移或本地/远端分配证据 | `functions/mempool/FN-4/` |
| `FN-5` | 5 | 任务级与用户级内存隔离 | `RPC_ISO_ALLOW`、`RPC_ISO_DENY`、租户前缀写入闭环 | `functions/mempool/FN-5/` |
| `FN-6` | 6 | 内存池高可靠机制 | `RPC_CLUSTER_STATUS`、`degraded_puts`、peer 故障降级 | `functions/mempool/FN-6/` |

## 6. 各 FN 文档应覆盖的验证口径

### 存储 FN-1 异构存储统一访问接口

- 验证 DRAM、NVMe、HDD 或当前实现中已配置层级的统一接口可用。
- 核心证据：`RPC_TIER_STATS` 返回 `ok=true`，并能看到各层级状态或容量字段。
- 不要求在该功能测试中统计读写 GB/s，性能指标应归入 `performances/PF-6`。

### 存储 FN-2 多层感知与冷热分离

- 验证对象写入后可通过调度或手动 demote/promotion 路径进入目标层级。
- 核心证据：demote/promotion RPC 返回成功，或 tier stats 显示对象层级变化。
- 应区分“手动冷热迁移路径可用”和“自动访问频率驱动迁移策略生效”。

### 存储 FN-3 多策略预取

- 验证顺序访问、stride 或 markov 等预取计数器可被触发。
- 核心证据：`RPC_PREFETCH_STATS` 返回 `ok=true`，并包含策略计数或总访问计数。
- 不要求证明预取带来的性能提升，性能收益应另行进入性能测试。

### 存储 FN-4 压缩与去重

- 验证可压缩对象或重复对象触发压缩、去重统计。
- 核心证据：`RPC_COMPRESS_STATS`、去重统计或日志显示对象数、节省字节数、算法名称。
- 应说明当前使用 ZSTD、LZ4、哈希去重或降级实现。

### 存储 FN-5 IO 调度与优先级管理

- 验证前台 I/O 与后台 I/O 队列或调度器初始化成功。
- 核心证据：`IoScheduler init fg=... bg=...` 等日志，或可查询的队列状态。
- 不要求验证优先级吞吐提升比例，相关性能口径应放入性能测试。

### 存储 FN-6 仿真数据运行中采集

- 验证仿真运行期间可以采集对象属性、交互事件等数据流。
- 核心证据：`RPC_SIM_RUN` 执行成功，`RPC_SIM_CAPTURE_STATS` 中 pushed/flushed 事件数大于 0。
- 应说明 WAL、flush、dropped 计数的判定口径。

### RDMA FN-1 RDMA 与 TCP/IP 统一通信层

- 验证 RDMA QP 与 TCP fallback 能同时初始化或按配置切换。
- 核心证据：数据面日志中存在 RDMA QP 创建和 `TcpFallback listen`。
- 如当前环境 RDMA 不可用，应明确是 `SKIP` 还是只验证 TCP 降级。

### RDMA FN-2 聚合数据传输

- 验证聚合器启动并能处理小对象批量传输路径。
- 核心证据：`BatchAggregator started` 日志、批处理 RPC 或批量 PUT 成功证据。
- 不要求统计批处理吞吐或延迟阈值，相关指标归入 `performances/PF-4`、`PF-5`。

### RDMA FN-3 流量优先级机制

- 验证 QoS 调度器、高低优先级队列或 QP 分组可用。
- 核心证据：`QosSched ready` 日志，或高低优先级路径均可提交事件。
- 不要求达到 22% 效率提升，提升比例归入 `performances/PF-3`。

### RDMA FN-4 CPU 与 GPU 高速直通访问

- 验证 xfusion4 存在可用 NVIDIA GPU、CUDA、`nvidia_peermem` 或 `nv_peer_mem`、RDMA 设备 `mlx5_0`。
- 验证 xfusion4 数据面使用 `cudaMalloc` 分配 GPU buffer，并通过 `ibv_reg_mr` 注册为 RDMA MR，暴露有效 base/len/rkey。
- 验证 xfusion3 通过 RDMA WRITE 直接写入 xfusion4 的 GPU MR，并由 xfusion4 CUDA kernel 校验 GPU buffer 内容正确。
- 可选但建议验证 xfusion3 再通过 RDMA READ 从 xfusion4 GPU MR 读回，并校验 pattern 一致。
- 必须说明边界：CPU 只提交 WR，数据 payload 由 RNIC 直接进入 GPU 显存；不能用普通 CPU buffer、TCP、全量 `cudaMemcpy` payload 或脚本 JSON 代替 GPU Direct 验收。

### RDMA FN-5 路由转发与负载均衡

- 验证 key 到 primary 节点的路由查询可用，并可批量观察分布。
- 核心证据：`RPC_ROUTE_QUERY` 或 `/api/route/query` 返回 `ok=true` 和 `primary`。
- 可选证据：批量 scan 的节点分布计数。

### 内存池 FN-1 RDMA 语义远程内存访问与零拷贝

- 验证对象 PUT 走数据面远程访问路径并返回成功。
- 核心证据：`RPC_KV_PUT` 返回 `ok=true`，包含复制或 RDMA 相关时延字段。
- 应说明“零拷贝”的当前可观测证据，避免只凭 HTTP 控制面成功判断。

### 内存池 FN-2 分布式内存池 API

- 验证 `PUT`、`GET` 基本闭环。
- 核心证据：写入对象后读取到同一内容，`PoolRegistry` 或 UDS API 工作正常。
- 应避免仅验证 Flask 层参数解析，应尽量走 UDS 或数据面闭环。

### 内存池 FN-3 内存池统一命名机制

- 验证共享内存区域、pool、slab、rkey 等命名和交换信息存在。
- 核心证据：`RPC_CLUSTER_STATUS` 中 `peer_slab_base`、`peer_slab_rkey` 等字段非空且有效。
- 如果 peer 未在线，应返回 `SKIP` 或 `FAIL`，由文档明确判据。

### 内存池 FN-4 跨节点自适应分配与热数据迁移

- 验证本地/远端内存分配策略或热数据迁移机制可观测。
- 核心证据：`TierEngine` 初始化、迁移 RPC、热数据命中或迁移日志。
- 应区分存储层迁移和 RDMA 内存池远端/本地迁移，避免概念混用。

### 内存池 FN-5 任务级与用户级内存隔离

- 验证租户未授权写入失败、授权后写入成功、撤销后再次失败。
- 核心证据：`RPC_ISO_ALLOW`、`RPC_ISO_DENY` 与租户前缀 `RPC_KV_PUT` 的拒绝/允许/拒绝闭环。
- 建议使用临时 tenant id，避免污染演示环境。

### 内存池 FN-6 高可靠机制

- 验证 peer 状态字段、降级写计数和故障期间可用性。
- 核心证据：`RPC_CLUSTER_STATUS` 中 `peer_alive`、`degraded_puts` 字段存在；如开启主动演练，peer 故障期间 PUT 返回 `degraded=true`。
- 允许测试脚本在显式开启时主动 kill peer，用于完整验证高可靠降级闭环。
- 主动 kill peer 必须由显式环境变量开启，默认只做只读或非破坏性验证。
- 主动演练必须要求调用方提供 peer 连接和恢复参数，例如 `PEER_SSH`、`PEER_DP_PATH`、`PEER_START_CMD`，并在日志中记录 kill 与恢复动作。

## 7. 统一运行约定

后续实现每个 FN 时建议支持以下统一参数：

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `OUT_DIR` | 环境变量 | 当前 `functions/<module>/FN-N` 目录 | 本功能点输出目录 |
| `LOG_DIR` | 环境变量 | 当前 `FN-N/logs` 目录 | 本功能点日志目录 |
| `UDS` | 环境变量 | `/tmp/native_rdma-dp.sock` | 数据面 Unix domain socket |
| `CTRL_URL` | 环境变量 | `http://127.0.0.1:5000` | 控制面 HTTP 地址 |
| `REQUIRE_PEER` | 环境变量 | `1` | 是否要求 peer 在线 |
| `ALLOW_DESTRUCTIVE` | 环境变量 | `0` | 是否允许主动故障演练，例如 kill peer |
| `CURRENT_NODE` | 环境变量 | 按 native_rdma 配置 | 当前节点角色 |

所有脚本应支持：

```bash
cd "functions/<module>/FN-N"
bash run.sh
```

脚本也应支持从仓库根目录直接执行：

```bash
bash "functions/<module>/FN-N/run.sh"
```

## 8. 与现有脚本的关系

现有脚本可作为新 `functions/` 功能测试的蓝本，但 `functions/<module>/FN-N/` 必须成为面向功能验收的独立主入口。

迁移时建议遵循：

- 保留 `native_rdma/scripts/acceptance_all.sh`，避免破坏当前综合验收入口。
- 每个 `FN-N/run.py` 可以复用 `acceptance_all.sh` 中对应功能点的 UDS、HTTP 调用逻辑和判定思路，但不得在运行时依赖 `native_rdma/scripts/` 下的脚本文件。
- 必须保证即使删除 `native_rdma/scripts/` 目录，直接执行 `functions/` 下各功能测试脚本仍能正常运行。
- 共享逻辑如 UDS RPC 客户端、HTTP 请求、summary 写入、日志写入，应放在 `functions/` 自己的公共代码中，例如 `functions/common/`，不能依赖 `native_rdma/scripts/acceptance_all.sh`。
- `demo_walkthrough.sh` 更适合作为演示剧本，不应作为单点功能测试的唯一实现。
- `health_check.sh` 可作为前置环境检查参考，不应替代具体功能点验证。
- 新目录的输出统一写入当前 `functions/<module>/FN-N/` 目录和其 `logs/` 子目录。
- 新目录的 `summary.md` 使用统一的人类可读格式，只保留最近一次执行结果。
- 如后续保留 `native_rdma/tests/run_all_functional.sh`，可将其改为调用 `functions/` 下各 `FN-N/run.sh`。

## 9. 总入口要求

`functions/` 根目录必须从第一轮实现时就创建总入口和总汇总文件。总入口可以先以最小可用形式存在，后续再逐步完善聚合逻辑。

```text
functions/
├── run_all.sh
├── run_all.py
├── summary.md
├── common/
├── storage/
├── rdma/
└── mempool/
```

总入口应按模块汇总：

- 每个模块功能点总数。
- `PASS`、`FAIL`、`SKIP`、`WAIVED` 数量。
- 未完成项列表。
- 每个功能点的 `summary.md` 路径。
- 最近一次 `run_all.sh` 的执行时间和日志路径。

`functions/summary.md` 只保留最近一次批量执行结果，不保留历史统计。每个 `FN-N/summary.md` 也只保留最近一次单项执行结果。

## 10. 下个会话执行要求

本文件用于让下一个 AI 会话启动后可以直接按文档自动执行。下个会话开始实现 `functions/` 时，必须先新建或更新一个完成度文档：

```text
docs/functions实现完成度.md
```

该完成度文档用于记录当前实现进度，必须随着实现过程持续更新，不能只在最后补写。建议结构：

```markdown
# functions 实现完成度

## 当前结论

- 更新时间：
- 总体进度：
- 当前阶段：
- 当前阻塞：

## 根目录进度

| 项目 | 状态 | 说明 |
|---|---|---|
| functions/ | 未开始/进行中/完成 |  |
| functions/common/ | 未开始/进行中/完成 |  |
| functions/run_all.sh | 未开始/进行中/完成 |  |
| functions/run_all.py | 未开始/进行中/完成 |  |
| functions/summary.md | 未开始/进行中/完成 |  |

## 功能点进度

| 模块 | 功能点 | 状态 | 脚本 | 最近验证 | 说明 |
|---|---|---|---|---|---|
| storage | FN-1 | 未开始/进行中/完成 |  |  |  |
| rdma | FN-1 | 未开始/进行中/完成 |  |  |  |
| mempool | FN-1 | 未开始/进行中/完成 |  |  |  |

## 已执行验证

| 时间 | 命令 | 结果 | 说明 |
|---|---|---|---|
```

当前截至本文档编写时的事实：

- 已完成本需求文档：`docs/功能指标拆分与functions目录需求.md`。
- 尚未创建 `functions/` 目录。
- 尚未创建 `docs/functions实现完成度.md`。
- 尚未实现任何 `FN-N` 功能测试脚本。

## 11. 已确认决策与剩余事项

以下事项已经确认，后续实现时不应再次作为待确认问题阻塞：

1. 三个模块目录固定使用简洁英文名：`storage/`、`rdma/`、`mempool/`。
2. `FN-N` 编号在每个模块内独立从 `FN-1` 开始。
3. 每个 `FN-N/summary.md` 只保留最近一次执行结果，不保留历史统计。
4. `functions/summary.md` 只保留最近一次批量执行结果，不保留历史统计。
5. RDMA 模块 `FN-4` 的 GPU 直通功能已按 xfusion3 无 GPU、xfusion4 暴露 GPU MR 的拓扑实现真实 GPU Direct RDMA 验收。
6. 内存池高可靠功能允许在显式开启时主动 kill peer，但必须默认非破坏性。
7. `functions/` 根目录需要创建 `run_all.sh`、`run_all.py` 和总 `summary.md`。
8. 功能测试必须独立于 `native_rdma/scripts/`，可以复用其 UDS/HTTP 调用思路，但不能依赖其脚本文件存在。

剩余需要实现时细化的事项：

1. `functions/common/` 的公共代码组织方式。
2. 每个 `FN-N` 的具体 PASS、FAIL、SKIP、WAIVED 字段格式。
3. 每个功能点是否优先走 UDS 直连，还是允许在部分场景走 Flask HTTP。
4. 主动 HA 演练的 peer 恢复失败时如何退出和提示。
