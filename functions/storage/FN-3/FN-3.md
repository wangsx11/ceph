# FN-3 多策略预取机制测试说明

## 功能点

验证 stride 与 Markov 两种预取策略可预测后续对象，并能将预测到的低层对象提前加载到 DRAM。

## 来源要求

`docs/功能要求.md` / 多级异构的高效能存储模块 / 第 3 条。

## 实现位置

- `native_rdma/data_plane/storage/prefetcher.cpp`
- `RPC_PREFETCH_STATS`
- `RPC_KV_GET`
- `RPC_TIER_DEMOTE`
- `TierEngine::promote`

## 完成判据

本功能点同时验证两类策略：

1. Stride 预取：连续访问带数字后缀的 key 后，`RPC_PREFETCH_STATS` 返回的 `predicted` 包含下一顺序 key；该 key 预先被迁移到 `nvme`，触发访问历史后应被数据面预取加载到 DRAM，后续 `RPC_KV_GET` 返回 `hit=local`。
2. Markov 预取：重复访问 `A -> B` 转移后，`RPC_PREFETCH_STATS(A)` 返回的 `predicted` 包含高频 next key `B`；`B` 预先被迁移到 `nvme`，再次访问 `A` 后应被数据面预取加载到 DRAM，后续 `RPC_KV_GET(B)` 返回 `hit=local`。

两类策略均要求 `prefetch_loaded` 和 `prefetch_hits` 统计增加。

## 测试方案

前置条件：数据面 UDS 在线。

当前验证口径：写入并读取唯一 key 集合，分别构造 stride 和 Markov 访问模式，检查预测结果、实际预取加载和后续本地命中。

不验证内容：不统计预取带来的吞吐或延迟收益。

## 交互

1. 启动数据面。
2. 执行 `bash functions/storage/FN-3/run.sh`。
3. 查看 `summary.md` 和 `logs/` 中的原始 RPC 响应。

## 实现

### 当前验证口径

脚本通过 UDS 调用 `RPC_KV_PUT`、`RPC_TIER_DEMOTE`、`RPC_KV_GET` 和 `RPC_PREFETCH_STATS`。

测试会先将预测目标对象迁移到 `nvme`，随后通过访问历史触发预取逻辑。如果预取执行成功，目标对象在真正读取时应已经位于 DRAM，因此 `RPC_KV_GET` 返回 `hit=local`，同时 `RPC_PREFETCH_STATS` 中的 `prefetch_loaded` 和 `prefetch_hits` 增加。

`RPC_PREFETCH_STATS` 只用于查询当前预测候选和计数，不会因为查询本身增加 `hits_stride` 或 `hits_markov`。`prefetch_loaded` 和 `prefetch_hits` 只能由真实 `RPC_KV_GET` 数据面路径触发。

### 脚本入口

- `run.sh`
- `run.py`

输出文件写入当前 `functions/storage/FN-3/` 目录和 `logs/` 子目录。

## 命令

```bash
bash functions/storage/FN-3/run.sh
```
