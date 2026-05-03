# FN-1 RDMA 与 TCP/IP 统一通信层测试说明

## 功能点

验证 RDMA QP 初始化和 TCP fallback/OOB 控制通道初始化。

## 来源要求

`docs/功能要求.md` / RDMA 分布式仿真计算模块 / 第 1 条。

## 实现位置

- `native_rdma/data_plane/rdma/rdma_core.cpp`
- `native_rdma/data_plane/rdma/tcp_fallback.cpp`
- `native_rdma/data_plane/rdma/oob.cpp`
- `native_rdma/logs/dp_<role>.log`

## 完成判据

数据面日志包含 `created ... QPs`，并包含 `TcpFallback listen` 或 `TcpFallback connected`；`RPC_CLUSTER_STATUS` 中 `peer_num_qp` 有效。

## 测试方案

前置条件：数据面 UDS 在线；当前角色数据面日志可读。

当前验证口径：结合 UDS 集群状态和数据面启动日志判断统一通信层是否初始化。

不验证内容：不统计网络带宽和端到端延迟。

## 交互

1. 启动双节点数据面。
2. 执行 `bash functions/rdma/FN-1/run.sh`。
3. 查看 `summary.md` 和日志证据。

## 实现

### 当前验证口径

脚本调用 `RPC_CLUSTER_STATUS` 并扫描 `native_rdma/logs/dp_<role>.log`。

### 脚本入口

- `run.sh`
- `run.py`

输出文件写入当前 `functions/rdma/FN-1/` 目录和 `logs/` 子目录。

## 命令

```bash
bash functions/rdma/FN-1/run.sh
```

