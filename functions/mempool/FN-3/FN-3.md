# FN-3 内存池统一命名机制测试说明

## 功能点

验证共享内存区域、pool、slab、rkey 等命名和交换信息存在。

## 来源要求

`docs/功能要求.md` / 一致性总线内存池化仿真计算模块 / 第 3 条。

## 实现位置

- `PoolRegistry`
- `OOB handshake`
- `RPC_CLUSTER_STATUS`

## 完成判据

`RPC_CLUSTER_STATUS` 返回 `peer_slab_base`、`peer_slab_rkey`、`peer_num_qp`，且值均有效。

## 测试方案

前置条件：数据面 UDS 在线；默认 `REQUIRE_PEER=1` 时 peer 必须在线。

当前验证口径：直接读取 UDS 集群状态中的 peer slab 元数据。

不验证内容：不验证多 pool 的完整命名空间枚举。

## 交互

1. 启动双节点数据面。
2. 执行 `bash functions/mempool/FN-3/run.sh`。
3. 查看 `summary.md`。

## 实现

### 当前验证口径

脚本调用 `RPC_CLUSTER_STATUS` 并验证 peer slab 字段。

### 脚本入口

- `run.sh`
- `run.py`

输出文件写入当前 `functions/mempool/FN-3/` 目录和 `logs/` 子目录。

## 命令

```bash
bash functions/mempool/FN-3/run.sh
```

