# FN-2 分布式内存池 API 测试说明

## 功能点

验证分布式内存池封装 API 的基本 PUT/GET 闭环，并验证普通 PUT 在 peer 在线时产生远端副本且可从 peer 读回。

## 来源要求

`docs/功能要求.md` / 一致性总线内存池化仿真计算模块 / 第 2 条。

## 实现位置

- `RPC_KV_PUT`
- `RPC_KV_GET`
- `RPC_TCP_GET_PEER`
- `RPC_CLUSTER_STATUS`
- `PoolRegistry`

## 完成判据

默认 `REQUIRE_PEER=1` 时，peer 在线；`RPC_CLUSTER_STATUS` 中本地和 peer 的 slab base/len/lkey/rkey/QP 元数据有效，且 TCP data channel 在线。

脚本通过普通 `RPC_KV_PUT` 写入唯一 key，要求返回 `ok=true`、`transport=rdma`、`degraded=false`，且 `offset/size` 落在本地和 peer slab 有效范围内。随后 `RPC_KV_GET` 必须从本地 API 读回同一 value，`RPC_TCP_GET_PEER` 必须从 peer 端读回同一 value。

## 测试方案

前置条件：数据面 UDS 在线；默认要求双节点 peer 在线；TCP data channel 在线用于 peer 读回校验。

当前验证口径：直接走 UDS 数据面闭环，不只验证 Flask 控制面参数解析；普通 `RPC_KV_PUT` 对调用方屏蔽 RDMA/OOB 细节，但脚本会检查返回字段和 peer 读回，确认它没有退化为本地单节点写入。

不验证内容：不验证性能指标或对象同步 UI；peer 读回使用 TCP data channel 触发 peer 本地读取，只作为远端副本内容校验。

## 交互

1. 启动双节点数据面。
2. 执行 `bash functions/mempool/FN-2/run.sh`。
3. 查看 `summary.md`、`raw.json` 和 `logs/` 中的 RPC 原始响应。

## 实现

### 当前验证口径

脚本调用 `RPC_CLUSTER_STATUS`、`RPC_KV_PUT`、`RPC_KV_GET` 和 `RPC_TCP_GET_PEER`。

### 脚本入口

- `run.sh`
- `run.py`

输出文件写入当前 `functions/mempool/FN-2/` 目录和 `logs/` 子目录。

## 命令

```bash
bash functions/mempool/FN-2/run.sh
```
