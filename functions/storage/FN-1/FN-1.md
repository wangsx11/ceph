# FN-1 仿真引擎异构存储统一访问接口测试说明

## 功能点

验证多级异构存储层通过统一数据面接口暴露状态，并验证对象可通过同一数据面 API 写入、迁移到 NVMe/HDD、再读回。

## 来源要求

`docs/功能要求.md` / 多级异构的高效能存储模块 / 第 1 条。

## 实现位置

- `native_rdma/data_plane/storage/tier_engine.cpp`
- `native_rdma/data_plane/storage/io_scheduler.cpp`
- `RPC_TIER_STATS`
- `RPC_KV_PUT`
- `RPC_TIER_DEMOTE`
- `RPC_KV_GET`

## 完成判据

`RPC_TIER_STATS` 返回 `ok=true`，且包含 `dram`、`nvme`、`hdd` 层级字段；探针对象写入后可分别通过 `RPC_TIER_DEMOTE` 迁移到 `nvme` 与 `hdd`，再通过 `RPC_KV_GET` 读回原始内容，并返回对应层级提升命中证据。

最近一次验证结果：

- 运行时间：2026-05-04T11:10:03+0800
- 结果：`PASS`
- 关键证据：
  - `RPC_TIER_STATS` 暴露 `dram/nvme/hdd` 统一层级字段。
  - NVMe 闭环成功：`PUT -> RPC_TIER_DEMOTE(nvme) -> GET hit=nvme_promote`。
  - HDD 闭环成功：`PUT -> RPC_TIER_DEMOTE(hdd) -> GET hit=hdd_promote`。
  - 原始 RPC 调用链记录在 `raw.json` 和 `logs/run_20260504_111003.log`。

## 测试方案

前置条件：数据面 UDS 在线，默认路径为 `/tmp/native_rdma-dp.sock`。

当前验证口径：验证统一层级状态接口、DRAM 写入、NVMe/HDD 迁移与读回闭环；不统计读写吞吐或层级带宽。

不验证内容：性能指标归入 `performances/PF-6`。

## 交互

1. 启动 `native_rdma` 数据面。
2. 进入 `functions/storage/FN-1/`。
3. 执行 `bash run.sh`。
4. 查看本目录 `summary.md` 与 `logs/`。

## 实现

### 当前验证口径

脚本直连 UDS 调用 `RPC_TIER_STATS`、`RPC_KV_PUT`、`RPC_TIER_DEMOTE` 和 `RPC_KV_GET`。只有层级字段存在、NVMe 探针和 HDD 探针均能读回原始内容时才判定 `PASS`。

### 脚本入口

- `run.sh`
- `run.py`

输出文件写入当前 `functions/storage/FN-1/` 目录和 `logs/` 子目录。

## 命令

```bash
bash functions/storage/FN-1/run.sh
```
