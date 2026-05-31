# FN-5 分布式节点路由转发与负载均衡测试说明

## 功能点

验证 key 到 primary/replica 节点的一致性哈希路由查询、批量分布，以及 remote-primary key 的跨节点 routed PUT 转发闭环。

## 来源要求

`docs/功能要求.md` / RDMA 分布式仿真计算模块 / 第 5 条。

## 实现位置

- `native_rdma/data_plane/router/object_router.cpp`
- `RPC_ROUTE_QUERY`
- `native_rdma/data_plane/main.cpp` 的 `RPC_ROUTE_PUT`
- `RPC_TCP_GET_PEER` 作为 peer 读回验证通道

## 完成判据

默认 `REQUIRE_PEER=1` 时，`peer_alive` 必须为 `true`；否则只能证明路由表查询，不能证明跨节点转发。

批量 `RPC_ROUTE_QUERY` 均返回 `ok=true`，`primary` 非空，并观察到至少两个 primary 分布桶。脚本必须同时找到本地 primary key 和远端 primary key。

`RPC_ROUTE_PUT` 对本地 primary key 必须返回 `route_forwarded=false`，并可由本地 `RPC_KV_GET` 读回；对远端 primary key 必须返回 `route_forwarded=true`、`forward_transport=rdma`、`degraded=false`，并可由 `RPC_TCP_GET_PEER` 从 xfusion4 读回同一 value。

`replica` 为空时记录为当前路由策略细节，不单独判失败。

## 测试方案

前置条件：数据面 UDS 在线；xfusion4 peer 在线；RDMA transport 在线；TCP data channel 在线用于 peer 读回校验。

当前验证口径：对至少 64 个 key 执行路由查询，统计 primary 分布；随后分别执行本地 primary routed PUT 和远端 primary routed PUT，验证本地读回与 peer 读回。

不验证内容：不验证多跳网络转发性能；`RPC_TCP_GET_PEER` 只作为 peer 内容读回校验通道。

## 交互

1. 启动双节点数据面。
2. 执行 `bash functions/rdma/FN-5/run.sh`。
3. 查看 `summary.md`、`raw.json` 和过程日志。

## 实现

### 当前验证口径

脚本调用 `RPC_CLUSTER_STATUS`、`RPC_ROUTE_QUERY`、`RPC_ROUTE_PUT`、`RPC_KV_GET` 和 `RPC_TCP_GET_PEER`。旧口径只证明路由查询与分布；当前口径额外验证 remote-primary key 的真实跨节点转发和读回闭环。

### 脚本入口

- `run.sh`
- `run.py`

输出文件写入当前 `functions/rdma/FN-5/` 目录和 `logs/` 子目录。

## 命令

```bash
cd native_rdma
bash start.sh
cd ..
bash functions/rdma/FN-5/run.sh
```

可选增加路由采样 key 数：

```bash
FN5_ROUTE_KEYS=128 bash functions/rdma/FN-5/run.sh
```
