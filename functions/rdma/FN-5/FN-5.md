# FN-5 分布式节点路由转发与负载均衡测试说明

## 功能点

验证 key 到 primary/replica 节点的一致性哈希路由查询，并观察批量分布。

## 来源要求

`docs/功能要求.md` / RDMA 分布式仿真计算模块 / 第 5 条。

## 实现位置

- `native_rdma/data_plane/router/object_router.cpp`
- `RPC_ROUTE_QUERY`

## 完成判据

批量 `RPC_ROUTE_QUERY` 均返回 `ok=true`，`primary` 非空，并观察到至少两个 primary 分布桶。`replica` 为空时记录为当前路由策略细节。

## 测试方案

前置条件：数据面 UDS 在线。

当前验证口径：对 32 个 key 执行路由查询，统计 primary 分布；不把单个 key 的 `replica` 为空直接判为失败。

不验证内容：不验证多跳网络转发性能。

## 交互

1. 启动数据面。
2. 执行 `bash functions/rdma/FN-5/run.sh`。
3. 查看批量路由统计。

## 实现

### 当前验证口径

脚本直接调用 `RPC_ROUTE_QUERY` 并统计 primary 节点出现次数。

### 脚本入口

- `run.sh`
- `run.py`

输出文件写入当前 `functions/rdma/FN-5/` 目录和 `logs/` 子目录。

## 命令

```bash
bash functions/rdma/FN-5/run.sh
```
