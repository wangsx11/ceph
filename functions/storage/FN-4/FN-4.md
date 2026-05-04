# FN-4 可配置压缩与去重测试说明

## 功能点

验证可配置压缩统计接口、可压缩对象进入冷层后的压缩统计变化，以及重复对象进入 HDD 冷层时的运行时去重统计变化。

## 来源要求

`docs/功能要求.md` / 多级异构的高效能存储模块 / 第 4 条。

## 实现位置

- `native_rdma/data_plane/storage/compress.cpp`
- `native_rdma/data_plane/storage/dedup.cpp`
- `RPC_COMPRESS_STATS`
- `RPC_DEDUP_STATS`
- `RPC_TIER_DEMOTE`
- `TierEngine::dedup_stats`

## 完成判据

在对象槽位可容纳 4096 字节探针时，写入两个内容相同的对象并 demote 到 `hdd` 后：

1. `RPC_COMPRESS_STATS` 的 `objects` 或 `saved_bytes` 增加；
2. `RPC_DEDUP_STATS` 的 `duplicate_objects` 和 `saved_bytes` 增加；
3. 两个对象均可通过 `RPC_KV_GET` 从 HDD 读回，并返回 `hdd_promote` 命中证据。

## 测试方案

前置条件：数据面 UDS 在线；`SLAB_SLOT_SIZE` 需要足以容纳 4096 字节对象。若槽位太小，脚本返回 `SKIP`。

当前验证口径：以 `RPC_COMPRESS_STATS` 的 `objects`、`saved_bytes` 字段作为压缩证据；以 `RPC_DEDUP_STATS` 的 `duplicate_objects`、`saved_bytes` 字段作为运行时去重证据。

不验证内容：不统计压缩或去重带来的吞吐、延迟收益。

## 交互

1. 启动数据面；如需完整压缩触发，使用足够大的 `SLAB_SLOT_SIZE`。
2. 执行 `bash functions/storage/FN-4/run.sh`。
3. 查看 `summary.md` 和 `raw.json`。

## 实现

### 当前验证口径

脚本读取压缩和去重统计基线，写入两个内容相同的可压缩对象，将两者 demote 到 HDD 后再次读取统计。第二个对象应复用第一个对象的冷层存储位置并增加去重统计。最后脚本通过 `RPC_KV_GET` 读回两个对象，确认压缩/去重后的对象仍可从 HDD 提升回 DRAM。

### 脚本入口

- `run.sh`
- `run.py`

输出文件写入当前 `functions/storage/FN-4/` 目录和 `logs/` 子目录。

## 命令

```bash
bash functions/storage/FN-4/run.sh
```
