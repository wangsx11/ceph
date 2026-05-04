# FN-6 内存池高可靠机制测试说明

## 功能点

验证 heartbeat peer 状态、peer 故障期间本节点继续可用的降级写入、降级计数递增，以及恢复后重新进入 RDMA 非降级复制路径。

## 来源要求

`docs/功能要求.md` / 一致性总线内存池化仿真计算模块 / 第 6 条。

## 实现位置

- `RPC_CLUSTER_STATUS`
- `native_rdma/data_plane/replication/heartbeat.{h,cpp}`
- `native_rdma/data_plane/main.cpp` 中 `RPC_KV_PUT` 的 HA degraded 分支
- `peer_alive`
- `degraded_puts`
- `degraded_bytes`
- `RPC_KV_GET`
- `RPC_TCP_GET_PEER`
- 主动演练参数：`ALLOW_DESTRUCTIVE=1`、`PEER_SSH`、`PEER_DP_PATH`、`FN6_RECOVERY_CMD`

## 完成判据

默认非破坏性模式下，`RPC_CLUSTER_STATUS` 返回 `peer_alive`、`degraded_puts`、`degraded_bytes` 字段，但只标记为“部分完成”。

完整验收需要显式开启主动演练：

1. 演练前 `RPC_CLUSTER_STATUS.peer_alive=true`，且 `transport=rdma`。
2. 通过 SSH kill peer 数据面进程。
3. 本端观测 `peer_alive=false`。
4. 故障期间 `RPC_KV_PUT` 返回 `ok=true`、`degraded=true`、`transport=rdma`。
5. 同一 key 通过本地 `RPC_KV_GET` 读回，证明 peer 故障期间本节点继续可用。
6. `degraded_puts` 与 `degraded_bytes` 相比故障前增加。
7. 执行 `FN6_RECOVERY_CMD` 恢复双节点后，`peer_alive=true`，后续 PUT 返回 `degraded=false` 且可通过 `RPC_TCP_GET_PEER` 从 peer 读回。

## 测试方案

前置条件：数据面 UDS 在线；完整验收要求 xfusion3/xfusion4 双节点 RDMA 在线。

默认验证口径：只读检查 HA 字段，完成情况标记为“部分完成”。

完整验证口径：`ALLOW_DESTRUCTIVE=1` 时执行主动 peer 故障演练，并通过恢复命令把双节点拉回健康状态。

不验证内容：不宣称 peer 进程重启后无需重启本端即可自动重新 OOB/QP 握手；恢复闭环使用 `start.sh` 重建双节点 RDMA 连接。

## 交互

1. 默认执行：`bash functions/mempool/FN-6/run.sh`。
2. 主动演练需显式提供：

```bash
ALLOW_DESTRUCTIVE=1 \
PEER_SSH=xfusion4 \
PEER_DP_PATH=/home/wangshouxin/native-rdma-web/native_rdma/build-current/bin/native_rdma_dp \
FN6_RECOVERY_CMD='cd native_rdma && LOCAL_HOST=xfusion3 NR_TRANSPORT=rdma NR_ASYNC_REPL=0 bash start.sh' \
bash functions/mempool/FN-6/run.sh
```

3. 查看 `summary.md` 与 `logs/`。

## 实现

### 当前验证口径

脚本调用 `RPC_CLUSTER_STATUS`；显式开启后通过 SSH kill peer，等待本端 heartbeat 变为 lost，再执行 PUT/GET 和计数校验，最后通过 `FN6_RECOVERY_CMD` 恢复双节点并验证恢复后的 RDMA 复制和 peer 读回。

### 脚本入口

- `run.sh`
- `run.py`

输出文件写入当前 `functions/mempool/FN-6/` 目录和 `logs/` 子目录。

## 命令

```bash
bash functions/mempool/FN-6/run.sh
```
