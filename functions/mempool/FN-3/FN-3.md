# FN-3 内存池统一命名机制测试说明

## 功能点

验证共享内存区域、pool、slab、rkey 等命名和交换信息在运行态真实登记，并且本地与远端使用同一个逻辑 pool 名称。

## 来源要求

`docs/功能要求.md` / 一致性总线内存池化仿真计算模块 / 第 3 条。

## 实现位置

- `native_rdma/data_plane/mempool/pool_registry.{h,cpp}`：维护本地 pool 与远端 peer pool 的命名登记。
- `native_rdma/data_plane/main.cpp`：启动时把本地 slab 注册为 `default/slab1k`；OOB handshake 成功后把 peer 导出的 slab/rkey 注册到同名 remote pool。
- `RPC_CLUSTER_STATUS`：暴露本地和 peer slab base/len/lkey/rkey/QP 元数据。
- `RPC_MEMPOOL_POOLS`：查询 `PoolRegistry` 中的本地/远端同名 pool，并返回 registry 元数据。

## 完成判据

1. `RPC_CLUSTER_STATUS` 返回本地 `local_slab_base/local_slab_len/local_slab_lkey/local_slab_rkey` 以及 peer `peer_slab_base/peer_slab_len/peer_slab_rkey/peer_num_qp`，且值均有效。
2. `RPC_MEMPOOL_POOLS` 返回本地和远端 pool 均为 `default/slab1k`。
3. 本地 registry 的 base/len/lkey/rkey 与 `RPC_CLUSTER_STATUS` 本地 slab 元数据一致。
4. 远端 registry 的 base/len/rkey 与 OOB/cluster 中的 peer slab 元数据一致。
5. 默认 `REQUIRE_PEER=1` 时必须 `peer_alive=true`，peer 不在线时不能用历史 OOB 字段或静态文件生成 PASS。

## 测试方案

前置条件：数据面 UDS 在线；默认 `REQUIRE_PEER=1` 时 peer 必须在线。

当前验证口径：脚本直连 C++ 数据面 UDS，先读取 `RPC_CLUSTER_STATUS`，再调用 `RPC_MEMPOOL_POOLS`，把 `PoolRegistry` 里的本地/远端同名 pool 与 OOB/cluster 元数据逐字段比对。

不验证内容：不验证多 pool 的完整命名空间枚举，也不验证运行时动态创建新 pool。

## 交互

1. 启动双节点数据面。
2. 执行 `bash functions/mempool/FN-3/run.sh`。
3. 查看 `summary.md`。

## 实现

### 当前验证口径

脚本调用 `RPC_CLUSTER_STATUS` 和 `RPC_MEMPOOL_POOLS`，验证本地/远端共享内存区域统一命名为 `default/slab1k`，并验证 registry 元数据与 OOB 交换出来的 RDMA MR 信息一致。

### 脚本入口

- `run.sh`
- `run.py`

输出文件写入当前 `functions/mempool/FN-3/` 目录和 `logs/` 子目录。

## 命令

```bash
bash functions/mempool/FN-3/run.sh
```
