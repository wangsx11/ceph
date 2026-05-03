# FN-4 可配置压缩与去重测试说明

## 功能点

验证可配置压缩统计接口和可压缩对象进入冷层后的压缩统计变化；记录去重代码接入事实。

## 来源要求

`docs/功能要求.md` / 多级异构的高效能存储模块 / 第 4 条。

## 实现位置

- `native_rdma/data_plane/storage/compress.cpp`
- `native_rdma/data_plane/storage/dedup.cpp`
- `RPC_COMPRESS_STATS`
- `RPC_TIER_DEMOTE`

## 完成判据

在对象槽位可容纳 4096 字节探针时，写入重复字符对象并 demote 到 `hdd` 后，压缩对象数或节省字节数增加。

## 测试方案

前置条件：数据面 UDS 在线；`SLAB_SLOT_SIZE` 需要足以容纳 4096 字节对象。若槽位太小，脚本返回 `SKIP`。

当前验证口径：以 `RPC_COMPRESS_STATS` 的 `objects`、`saved_bytes` 字段作为压缩证据；以 `dedup.cpp`、`dedup.h` 存在并纳入 `nr_storage` 构建作为去重代码证据。

不验证内容：当前数据面没有独立去重 RPC，因此不伪造去重运行时统计。

## 交互

1. 启动数据面；如需完整压缩触发，使用足够大的 `SLAB_SLOT_SIZE`。
2. 执行 `bash functions/storage/FN-4/run.sh`。
3. 查看 `summary.md` 和 `raw.json`。

## 实现

### 当前验证口径

脚本读取压缩统计基线，写入可压缩对象，demote 到 HDD 后再次读取压缩统计。

### 脚本入口

- `run.sh`
- `run.py`

输出文件写入当前 `functions/storage/FN-4/` 目录和 `logs/` 子目录。

## 命令

```bash
bash functions/storage/FN-4/run.sh
```
