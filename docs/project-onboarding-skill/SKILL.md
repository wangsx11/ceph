---
name: native-rdma-project-onboarding
description: 在 native_rdma 项目的新会话开始时使用本 skill，用于快速了解项目目标、当前实现结构、需求文档位置、硬件与部署上下文，以及修改前应该优先阅读的文件。
---

# native_rdma 项目上下文

当新的 AI 会话需要快速同步 `native_rdma` 自研 RDMA 分布式共享数据系统的上下文时，先阅读本文件。

## 先读什么

1. 先读本 `SKILL.md`。
2. 再按任务类型读取对应项目文档：
   - 总体方案：`docs/自研方案.md`
   - 实施清单：`docs/自研实施清单.md`
   - 功能需求：`docs/功能要求.md`
   - 性能指标：`docs/性能要求.md`
   - 演示要求：`docs/演示要求.md`
   - 硬件与部署约束：`docs/硬件配置.md`
3. 如果要改代码，先阅读 `native_rdma/` 下对应模块，再开始编辑。

## 项目概览

`native_rdma` 是面向双节点 RoCEv2 环境的自研 RDMA 分布式共享数据系统。热路径由 C++17 数据面承担，包含 RDMA verbs、slab 内存池、路由、副本、QoS、批处理、分级存储、仿真与捕获等组件。Python Flask 只作为控制面和演示 API 层。仓库根目录下的 `dashboard/` 是当前浏览器前端。

## 当前实现结构

主实现：

- `native_rdma/data_plane/`：C++ 数据面。
- `native_rdma/control_plane/`：Flask 控制面、UDS 客户端、演示编排。
- `native_rdma/proto/`：控制与指标相关 protobuf 定义。
- `native_rdma/deploy/`：节点 A/B 的 env 配置。
- `native_rdma/scripts/`：安装、调优、启动、停止、健康检查、验收脚本。
- `native_rdma/tests/`：当前自研实现的性能与功能验证。
- `dashboard/`：由 Flask 控制面服务的当前 Web 前端。

当前演示页面：

- Demo 3 跨节点对象同步：`dashboard/m3_sync.js`，API `/api/demo3/*`。
- Demo 5 吞吐与规模：`dashboard/m5_perf.js`，API `/api/demo5/*`。
- Demo 6 分级存储：`dashboard/m6_tiering.js`，API `/api/demo6/*`。

另外还有路由、隔离、HA、仿真捕获相关演示 API：

- 路由：`/api/route/*`，前端 `dashboard/m7_route.js`。
- 隔离：`/api/iso/*`，前端 `dashboard/m8_isolation.js`。
- HA：`/api/ha/*`，前端 `dashboard/m9_ha.js`。
- 仿真捕获：`/api/sim/*`，前端 `dashboard/m10_capture.js`。

## 需求对应关系

- 多级异构存储：`native_rdma/data_plane/storage/`，`dashboard/m6_tiering.js`。
- RDMA 分布式通信：`native_rdma/data_plane/rdma/`、`batch/`、`qos/`、`router/`。
- 一致性共享内存池：`native_rdma/data_plane/mempool/`、`replication/`、`api/`。
- 运行时仿真捕获：`native_rdma/data_plane/sim/`，`/api/sim/*`。
- 性能脚本：`native_rdma/tests/performance/*.sh`，汇总逻辑在 `native_rdma/tests/performance/summary.py`。

## 硬件与部署事实

完整信息见 `docs/硬件配置.md`。核心参数：

- 节点 A：`xfusion3`，RoCE IP `192.168.0.218`，HCA 位于 NUMA node0。
- 节点 B：`xfusion4`，RoCE IP `192.168.0.214`，HCA 位于 NUMA node1。
- RDMA 设备：`mlx5_0`。
- RoCEv2 IPv4 GID index：`3`。
- 数据端口：`18515`。
- 默认前端入口：节点 A Flask，`http://192.168.0.218:5000/`。

推荐在节点 A 上启动：

```bash
cd native_rdma
bash start.sh
```

`start.sh` 会同步与编译项目、清理演示冷层残留、停止旧进程，通过 `scripts/demo_up.sh` 启动节点 B，然后启动节点 A。

## 工程规则

- 优先以当前 `native_rdma/` 代码和根目录 `dashboard/` 为准。
- 修改启动行为前，先读 `native_rdma/start.sh`、`scripts/demo_up.sh`、`start_node.sh` 和两个 env 文件。
- 修改 API 前，先读 `native_rdma/control_plane/app.py`，再读 `native_rdma/data_plane/main.cpp` 中对应的数据面 RPC 处理逻辑。
- 修改前端行为前，确认对应 JS 文件是否被 `dashboard/index.html` 加载。
- 保留工作区里的用户改动；不要 reset 已删除的旧文件。

## 常用验证

C++ 改动：

```bash
cd native_rdma
cmake --build build -j
```

Python 控制面语法检查：

```bash
python3 -m py_compile native_rdma/control_plane/*.py
```

文档内容清理检查：

```bash
rg -n -i "需要检查的旧术语" docs native_rdma dashboard
```
