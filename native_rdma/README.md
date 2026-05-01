## native_rdma · 从零手搓的 RDMA 分布式共享数据系统

> 本项目完全独立于现有 `backend*/`（旧版后端），是基于 `docs/自研方案.md` 的全新实现。
> 本 README 使用占位符，方便跨项目复用。

### 占位符

| 占位符 | 含义 | 示例 |
|---|---|---|
| `<PROJECT_ROOT>` | 项目根目录 | `native_rdma/` |
| `<NODE_A_IP>` | 节点 A RoCE IP | `192.168.0.218` |
| `<NODE_B_IP>` | 节点 B RoCE IP | `192.168.0.214` |
| `<RDMA_DEV>` | RDMA verbs 设备名 | `mlx5_0` |
| `<GID_IDX>` | RoCE v2 IPv4 GID index | `3` |
| `<CTRL_PORT>` | 控制面 HTTP 端口 | `5000` |
| `<DATA_PORT>` | 数据面 RDMA CM 端口 | `18515` |
| `<WEB_PORT>` | 前端端口 | `8080` |

### 目录结构

```
<PROJECT_ROOT>/
├── CMakeLists.txt               # 顶层 CMake
├── README.md                    # 本文件
├── .gitignore
│
├── proto/                       # IDL：控制面↔数据面 协议
├── data_plane/                  # C++ 数据面 (热路径)
│   ├── common/                  # logger / numa / 队列 / 时间
│   ├── rdma/                    # QP / CQ / MR / CM / poller
│   ├── mempool/                 # Slab / Arena / HugePage MR
│   ├── qos/                     # 高低优先级 QP 调度
│   ├── batch/                   # 批聚合 (WR chain)
│   ├── router/                  # 一致性 hash 路由
│   ├── storage/                 # 分级存储 / 预取 / 压缩 / io_uring
│   ├── replication/             # 同步复制 + 心跳 HA
│   ├── sim/                     # 仿真引擎 / 实时采集
│   ├── api/                     # UDS RPC + 指标暴露
│   └── main.cpp
│
├── control_plane/               # Python Flask 控制面 (非热路径)
│   ├── app.py
│   ├── uds_client.py
│   ├── ws_metrics.py
│   ├── ws_events.py
│   ├── demo_controller.py
│   └── requirements.txt
│
├── dashboard/                   # 前端三大演示面板
├── scripts/                     # 依赖安装 / OS 调优 / 启停
├── deploy/                      # 两节点配置模板
├── tests/                       # 功能 + 性能测试
└── docs/                        # 子文档 (架构 / API / Benchmark)
```

### 快速开始

#### 1) 安装依赖（两台节点）

```bash
bash scripts/install_deps.sh
```

#### 2) OS 调优（两台节点）

```bash
sudo bash scripts/tune_os.sh
```

#### 3) 编译

```bash
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release -GNinja
cmake --build build -j
```

#### 4) 同步到对端

```bash
bash scripts/sync_to_peer.sh <NODE_B_IP>
```

#### 5) 启动

```bash
# 节点 B（被动方先起）
ssh <NODE_B_IP> "cd <PROJECT_ROOT> && bash scripts/start_node.sh --role=B"

# 节点 A
bash scripts/start_node.sh --role=A
```

#### 6) 验证

```bash
curl http://<NODE_A_IP>:<CTRL_PORT>/api/cluster/status
# 期望: {"peers":[{"id":"B","rdma_connected":true,"replica_lag_us":xx}]}
```

### 更多文档

- 方案总览：`../docs/自研方案.md`
- 实施清单：`../docs/自研实施清单.md`
- 架构细节：`docs/ARCHITECTURE.md`（待补）
- API 手册：`docs/API.md`（待补）
- 基准测试：`docs/BENCHMARK.md`（待补）
