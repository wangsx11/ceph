# FN-4 跨节点内存自适应分配与热数据迁移测试说明

## 功能点

验证冷对象可自适应放置到远端 RDMA slab，并在连续访问成为热点后通过 RDMA READ 迁回本地 slab。

## 来源要求

`docs/功能要求.md` / 一致性总线内存池化仿真计算模块 / 第 4 条。

## 实现位置

- `native_rdma/data_plane/main.cpp`：
  - `RPC_MEMPOOL_ADAPT_PUT`：按 cold-remote-first 策略把对象 RDMA WRITE 到 peer slab，只在本地保存远端位置元数据。
  - `RPC_MEMPOOL_ADAPT_GET`：访问远端对象；未达到热点阈值时保持远端放置并 RDMA READ，达到阈值后 RDMA READ 到本地 slab。
  - `RPC_MEMPOOL_ADAPT_STATS`：暴露远端对象、本地化对象、远端读和迁移计数。
  - `RPC_KV_GET`：热点迁移后从本地 `TierEngine`/slab 普通路径命中。
- `RdmaCore::post_write` / `RdmaCore::post_read`
- `PoolRegistry` / OOB 交换的 peer slab base、len、rkey
- `TcpDataChannel`：仅用于 peer 端读回校验远端放置内容。

## 完成判据

1. `RPC_CLUSTER_STATUS` 显示 `peer_alive=true`、`transport=rdma`，并且 peer slab base/len/rkey/QP 有效。
2. `RPC_MEMPOOL_ADAPT_PUT` 返回 `placement=remote`、`transport=rdma`、`degraded=false`，且 `remote_offset/size` 落在 peer slab 范围内。
3. `RPC_TCP_GET_PEER` 能从 peer 端读回同一 value，证明对象确实落在远端可见内存区域。
4. 首次 `RPC_MEMPOOL_ADAPT_GET` 返回 `hit=remote_rdma_read`、`placement_after=remote`、`migrated=false`，证明冷对象未被立即本地化。
5. 连续访问达到热点阈值后，`RPC_MEMPOOL_ADAPT_GET` 返回 `hit=remote_to_local_migrate`、`placement_after=local`、`local_offset` 有效。
6. 随后普通 `RPC_KV_GET` 返回 `hit=local` 且 value 一致，证明热点仿真数据已存放于本地内存。

## 测试方案

前置条件：数据面 UDS 在线；默认 `REQUIRE_PEER=1` 时 peer 必须在线；数据面需要以 `NR_TRANSPORT=rdma` 启动；TCP data channel 在线用于 peer 内容校验。

当前验证口径：脚本直连 C++ 数据面 UDS，先把冷对象放到远端 RDMA slab，再通过访问次数触发热点识别和 RDMA READ 本地化迁移。

不验证内容：不统计迁移收益或吞吐性能，不把存储层 NVMe/HDD demote 当作跨节点内存迁移证据。

## 交互

1. 以 RDMA transport 启动双节点数据面。
2. 执行 `bash functions/mempool/FN-4/run.sh`。
3. 查看 `summary.md`、`raw.json` 和 `logs/` 中的 RPC 原始证据。

## 实现

### 当前验证口径

脚本调用 `RPC_MEMPOOL_ADAPT_PUT`、`RPC_MEMPOOL_ADAPT_GET`、`RPC_MEMPOOL_ADAPT_STATS`、`RPC_TCP_GET_PEER` 和 `RPC_KV_GET`，验证远端优先放置、远端 RDMA READ、热点阈值触发本地化迁移以及普通本地 GET 命中。

### 脚本入口

- `run.sh`
- `run.py`

输出文件写入当前 `functions/mempool/FN-4/` 目录和 `logs/` 子目录。

## 命令

```bash
bash functions/mempool/FN-4/run.sh
```
