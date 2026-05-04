# FN-2 多层感知、冷热分离与调度测试说明

## 功能点

验证数据面能够识别对象所在层级，通过手动迁移和自动热度调度将冷对象下沉到较低存储层，并在读取时提升回 DRAM。

## 来源要求

`docs/功能要求.md` / 多级异构的高效能存储模块 / 第 2 条。

## 实现位置

- `RPC_KV_PUT`
- `RPC_TIER_DEMOTE`
- `RPC_TIER_STATS`
- `RPC_KV_GET`
- `TierEngine::demote`
- `TierEngine::promote`
- `TierEngine::calc_heat_score`
- `main.cpp` 中的 tier migrator 后台线程

## 完成判据

本功能点同时验证两类行为：

1. 手动迁移闭环：写入探针对象后，`RPC_TIER_DEMOTE` 到 `nvme` 成功；随后 `RPC_KV_GET` 返回 `hit=nvme_promote` 或同等 NVMe 提升证据，且读回内容与写入内容一致。
2. 自动冷热分离：写入一冷一热两个探针对象；测试期间持续访问热对象，只轮询 `RPC_TIER_STATS` 观察迁移事件，不读取冷对象；等待窗口结束后，冷对象应通过后台 tier migrator 下沉到 `nvme`，读取时返回 `hit=nvme_promote`，热对象持续访问期间不应出现下沉或读时提升。

## 测试方案

前置条件：数据面 UDS 在线。

当前验证口径：验证手动冷热迁移闭环，以及访问频率驱动的自动冷热分离行为。

不验证内容：不统计迁移性能、吞吐收益或局部性预取收益；局部性预测由 `storage/FN-3` 单独验证。

## 交互

1. 启动 `native_rdma` 数据面。
2. 执行 `bash functions/storage/FN-2/run.sh`。
3. 查看 `summary.md`、`raw.json` 与 `logs/run_*.json`。

## 实现

### 当前验证口径

脚本先写入手动迁移探针，调用 `RPC_TIER_DEMOTE` 将对象降到 `nvme`，再读取并检查命中来源和内容。

随后脚本写入冷对象和热对象。热对象在等待窗口中被周期性 `RPC_KV_GET` 访问，以保持热度；冷对象在等待窗口中不被读取，避免测试自身刷新热度。脚本同时轮询 `RPC_TIER_STATS` 记录迁移事件。最后读取冷对象并要求 `hit=nvme_promote`，同时确认热对象没有发生下沉或读时提升。

默认等待窗口由 `FN2_AUTO_WAIT_SECONDS` 控制，默认 `16` 秒；热对象访问间隔由 `FN2_HOT_ACCESS_INTERVAL_SECONDS` 控制，默认 `1` 秒。默认值匹配当前数据面热度参数：`demote_hot_score=0.30`、`time_decay_alpha=0.10`、`score_grace_ms=2000`。

### 脚本入口

- `run.sh`
- `run.py`

输出文件写入当前 `functions/storage/FN-2/` 目录和 `logs/` 子目录。

## 命令

```bash
bash functions/storage/FN-2/run.sh
```
