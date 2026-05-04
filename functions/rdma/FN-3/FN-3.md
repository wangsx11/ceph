# FN-3 流量优先级机制测试说明

## 功能点

验证 QoS 调度器初始化，高低优先级数据路径分别使用不同 RDMA QP 分组，并完成 peer 读回闭环。

## 来源要求

`docs/功能要求.md` / RDMA 分布式仿真计算模块 / 第 3 条。

## 实现位置

- `native_rdma/data_plane/qos/qos_sched.cpp`
- `native_rdma/data_plane/main.cpp` 的 QoS PUT 响应字段
- `RPC_KV_PUT_HI`
- `RPC_KV_PUT_LO`
- `RPC_TCP_GET_PEER` 作为 peer 读回验证通道

## 完成判据

最近一次数据面启动日志包含 `QosSched ready`、RDMA QP 初始化和 `OOB exchanged`。

默认 `REQUIRE_PEER=1` 时，`peer_alive` 必须为 `true`；否则只能证明本地降级写入，不能证明 RDMA 网络资源调度。

完整验收要求以默认 RDMA transport、`NR_ASYNC_REPL=0` 启动数据面。`RPC_KV_PUT_HI` 必须返回 `transport=rdma`、`degraded=false`，且响应中的 `qos.priority=hi`、`qos.qp_idx` 落在高优先级 QP 分组；`RPC_KV_PUT_LO` 必须返回 `transport=rdma`、`degraded=false`，且 `qos.priority=lo`、`qos.qp_idx` 落在低优先级 QP 分组。随后脚本用 `RPC_TCP_GET_PEER` 分别从 xfusion4 读回相同 value。

## 测试方案

前置条件：数据面 UDS 在线；当前角色数据面日志可读；xfusion4 peer 在线。

当前验证口径：扫描最近一次启动日志，并分别执行高优先级与低优先级 PUT；脚本检查两次 PUT 的 RDMA 传输状态、降级状态和实际 QP 分组，再用 peer 读回证明数据面写入完成。

不验证内容：不验证 22% 效率提升或吞吐比例，性能收益归入 `performances/PF-3`。

## 交互

1. 启动双节点数据面。
2. 执行 `bash functions/rdma/FN-3/run.sh`。
3. 查看 `summary.md`、`raw.json` 和过程日志。

## 实现

### 当前验证口径

脚本调用 `RPC_CLUSTER_STATUS`、`RPC_KV_PUT_HI`、`RPC_KV_PUT_LO` 和 `RPC_TCP_GET_PEER`，并只读取最近一次 `native_rdma_dp starting` 之后的 `QosSched ready` 日志，避免使用历史日志制造 PASS。

### 脚本入口

- `run.sh`
- `run.py`

输出文件写入当前 `functions/rdma/FN-3/` 目录和 `logs/` 子目录。

## 命令

```bash
cd native_rdma
bash start.sh
cd ..
bash functions/rdma/FN-3/run.sh
```
