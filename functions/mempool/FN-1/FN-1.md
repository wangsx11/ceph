# FN-1 RDMA 语义远程内存访问与零拷贝测试说明

## 功能点

验证对象 PUT 走用户态注册 slab 与 RDMA WRITE 复制路径，并能从 peer 端读回同一对象。

## 来源要求

`docs/功能要求.md` / 一致性总线内存池化仿真计算模块 / 第 1 条。

## 实现位置

- `RPC_KV_PUT_RDMA`
- `RPC_TCP_GET_PEER`
- `RdmaCore::post_write`
- `SlabPool`
- `RPC_CLUSTER_STATUS`

## 完成判据

默认 `REQUIRE_PEER=1` 时，peer 在线；`RPC_CLUSTER_STATUS` 中 `peer_slab_base`、`peer_slab_len`、`peer_slab_rkey`、`peer_num_qp` 均有效，且 TCP data channel 在线用于 peer 读回校验。

脚本强制调用 `RPC_KV_PUT_RDMA`，要求返回 `ok=true`、`transport=rdma`、`degraded=false`、`repl_ns>0`，并且返回的 `offset/size` 落在 peer slab 有效范围内。随后脚本调用 `RPC_TCP_GET_PEER` 从 peer 读回同一 value，证明远端 slab 数据和 peer 端索引闭环成立。

## 测试方案

前置条件：数据面 UDS 在线；默认需要 peer 在线；TCP data channel 在线。`REQUIRE_PEER=0` 只用于调试，不能作为完整验收证据。

当前验证口径：以 peer slab 元数据、PUT offset/size、`transport=rdma`、`repl_ns`、`degraded=false`、peer 端读回同值作为当前可观测的 RDMA 语义远程写证据。

不验证内容：不从硬件计数器证明全链路零拷贝；peer 读回使用 TCP data channel 触发 peer 本地读取，只作为远端内容校验，不把读回通道描述为 RDMA READ。

## 交互

1. 启动双节点数据面。
2. 执行 `bash functions/mempool/FN-1/run.sh`。
3. 查看 `summary.md` 与 `raw.json`。

## 实现

### 当前验证口径

脚本调用 `RPC_CLUSTER_STATUS`、`RPC_KV_PUT_RDMA` 和 `RPC_TCP_GET_PEER`。

### 脚本入口

- `run.sh`
- `run.py`

输出文件写入当前 `functions/mempool/FN-1/` 目录和 `logs/` 子目录。

## 命令

```bash
bash functions/mempool/FN-1/run.sh
```
