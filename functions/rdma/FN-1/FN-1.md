# FN-1 RDMA 与 TCP/IP 统一通信层测试说明

## 功能点

验证 RDMA QP 初始化、TCP fallback/OOB 控制通道初始化、完整验收所需的当前 peer 在线状态，以及传统 TCP/IP 数据传输闭环。

## 来源要求

`docs/功能要求.md` / RDMA 分布式仿真计算模块 / 第 1 条。

## 实现位置

- `native_rdma/data_plane/rdma/rdma_core.cpp`
- `native_rdma/data_plane/rdma/tcp_fallback.cpp`
- `native_rdma/data_plane/rdma/tcp_data_channel.cpp`
- `native_rdma/data_plane/rdma/oob.cpp`
- `native_rdma/logs/dp_<role>.log`

## 完成判据

最近一次数据面启动日志包含 `created ... QPs`、`TcpFallback listen` 或 `TcpFallback connected`，并包含 `OOB exchanged`；`RPC_CLUSTER_STATUS` 中 `peer_num_qp`、`peer_slab_base`、`peer_slab_rkey` 有效。

默认 `REQUIRE_PEER=1` 时，`peer_alive` 必须为 `true` 才能判定完整通过；如果 `peer_alive=false`，脚本返回 `SKIP`，不能把历史初始化日志当作当前双节点通信在线证据。

TCP 数据面闭环要求以 `NR_TRANSPORT=tcp`、`NR_ASYNC_REPL=0` 启动数据面，`tcp_data_ready=true`，普通 `RPC_KV_PUT` 返回 `transport=tcp` 且 `degraded=false`，随后 `RPC_TCP_GET_PEER` 从 peer 读回同一 value。

RDMA/TCP 对比展示要求同一脚本采集两组同步复制时延样本：

- `RPC_KV_PUT_RDMA`：强制走 RDMA WRITE 复制路径。
- 普通 `RPC_KV_PUT`：在 `NR_TRANSPORT=tcp` 下走 TCP data channel。

脚本汇总两组同步复制时延的 avg、p50、p95、min、max 和样本数。展示时统一使用微秒（us）；`raw.json` 中保留纳秒（ns）原始值和换算后的 us 字段。该结果用于功能测试展示两种协议路径的时延差异，不替代正式性能测试。

## 测试方案

前置条件：数据面 UDS 在线；当前角色数据面日志可读；完整验收要求 xfusion4 peer 在线。

当前验证口径：结合 UDS 集群状态和最近一次数据面启动日志判断统一通信层是否初始化且当前双节点在线；随后验证普通 `RPC_KV_PUT` 在 `NR_TRANSPORT=tcp` 下切换到 TCP 数据通道，并完成 peer GET 同值校验；最后采集 RDMA/TCP 两组同步复制时延样本。

不验证内容：不统计正式带宽指标；时延样本只作为 FN-1 功能展示中的微基准证据，正式性能指标仍归入 `performances/`。如需更稳定展示，可通过 `FN1_COMPARE_OPS=100` 增加样本数后重跑。

## 交互

1. 启动双节点数据面。
2. 执行 `bash functions/rdma/FN-1/run.sh`。
3. 查看 `summary.md` 和日志证据。

## 实现

### 当前验证口径

脚本调用 `RPC_CLUSTER_STATUS`，并只扫描 `native_rdma/logs/dp_<role>.log` 中最近一次 `native_rdma_dp starting` 之后的启动段，避免使用旧日志制造 PASS。启动证据满足后，脚本调用普通 `RPC_KV_PUT` 和 `RPC_TCP_GET_PEER` 验证显式协议切换后的 TCP/IP 数据传输闭环；随后调用 `RPC_KV_PUT_RDMA` 与普通 `RPC_KV_PUT` 采集 RDMA/TCP 时延对比。

### 脚本入口

- `run.sh`
- `run.py`

输出文件写入当前 `functions/rdma/FN-1/` 目录和 `logs/` 子目录。

## 命令

```bash
cd native_rdma
NR_TRANSPORT=tcp NR_ASYNC_REPL=0 bash start.sh
cd ..
bash functions/rdma/FN-1/run.sh
```

可选增加对比样本数：

```bash
FN1_COMPARE_OPS=100 bash functions/rdma/FN-1/run.sh
```

最近一次双节点结果的微秒换算示例：

- RDMA：avg 23.005us，p50 19.675us，p95 21.657us。
- TCP：avg 199.431us，p50 202.415us，p95 215.146us。
