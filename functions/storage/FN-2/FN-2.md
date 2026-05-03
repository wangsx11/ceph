# FN-2 多层感知、冷热分离与调度测试说明

## 功能点

验证对象可通过冷热迁移路径进入较低存储层，并在读取时被提升。

## 来源要求

`docs/功能要求.md` / 多级异构的高效能存储模块 / 第 2 条。

## 实现位置

- `RPC_KV_PUT`
- `RPC_TIER_DEMOTE`
- `RPC_KV_GET`
- `TierEngine::demote`
- `TierEngine::promote`

## 完成判据

写入探针对象后，`RPC_TIER_DEMOTE` 到 `nvme` 成功；随后 `RPC_KV_GET` 返回 `hit=nvme_promote` 或同等 NVMe 提升证据。

## 测试方案

前置条件：数据面 UDS 在线。

当前验证口径：验证手动冷热迁移闭环。

不验证内容：不证明自动访问频率驱动迁移策略，也不统计迁移性能。

## 交互

1. 启动 `native_rdma` 数据面。
2. 执行 `bash functions/storage/FN-2/run.sh`。
3. 查看 `summary.md`、`raw.json` 与 `logs/run_*.json`。

## 实现

### 当前验证口径

脚本写入唯一 key，调用 `RPC_TIER_DEMOTE` 将对象降到 `nvme`，再读取并检查命中来源。

### 脚本入口

- `run.sh`
- `run.py`

输出文件写入当前 `functions/storage/FN-2/` 目录和 `logs/` 子目录。

## 命令

```bash
bash functions/storage/FN-2/run.sh
```

