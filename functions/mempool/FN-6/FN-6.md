# FN-6 内存池高可靠机制测试说明

## 功能点

验证 peer 状态字段、降级写计数和可选主动故障演练入口。

## 来源要求

`docs/功能要求.md` / 一致性总线内存池化仿真计算模块 / 第 6 条。

## 实现位置

- `RPC_CLUSTER_STATUS`
- `peer_alive`
- `degraded_puts`
- `degraded_bytes`
- 可选 `PEER_SSH`、`PEER_DP_PATH`、`PEER_START_CMD`

## 完成判据

默认非破坏性模式下，`RPC_CLUSTER_STATUS` 返回 `peer_alive`、`degraded_puts`、`degraded_bytes` 字段；显式开启主动演练时，peer 故障期间 PUT 返回降级写入并使计数增加。

## 测试方案

前置条件：数据面 UDS 在线。

当前验证口径：默认只读检查 HA 字段，完成情况标记为“部分完成”；只有 `ALLOW_DESTRUCTIVE=1` 且提供 peer 参数时才主动 kill peer。

不验证内容：默认不执行破坏性故障演练。

## 交互

1. 默认执行：`bash functions/mempool/FN-6/run.sh`。
2. 主动演练需显式提供：`ALLOW_DESTRUCTIVE=1 PEER_SSH=... PEER_DP_PATH=... PEER_START_CMD=... bash functions/mempool/FN-6/run.sh`。
3. 查看 `summary.md` 与 `logs/`。

## 实现

### 当前验证口径

脚本调用 `RPC_CLUSTER_STATUS`；显式开启后通过 SSH kill peer，并在可选恢复命令存在时尝试恢复。

### 脚本入口

- `run.sh`
- `run.py`

输出文件写入当前 `functions/mempool/FN-6/` 目录和 `logs/` 子目录。

## 命令

```bash
bash functions/mempool/FN-6/run.sh
```

