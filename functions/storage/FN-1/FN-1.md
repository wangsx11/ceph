# FN-1 仿真引擎异构存储统一访问接口测试说明

## 功能点

验证多级异构存储层通过统一数据面接口暴露状态。

## 来源要求

`docs/功能要求.md` / 多级异构的高效能存储模块 / 第 1 条。

## 实现位置

- `native_rdma/data_plane/storage/tier_engine.cpp`
- `native_rdma/data_plane/storage/io_scheduler.cpp`
- `RPC_TIER_STATS`

## 完成判据

`RPC_TIER_STATS` 返回 `ok=true`，且包含 `dram`、`nvme`、`hdd` 层级字段。

## 测试方案

前置条件：数据面 UDS 在线，默认路径为 `/tmp/native_rdma-dp.sock`。

当前验证口径：只验证统一层级状态接口，不统计读写吞吐或层级带宽。

不验证内容：性能指标归入 `performances/PF-6`。

## 交互

1. 启动 `native_rdma` 数据面。
2. 进入 `functions/storage/FN-1/`。
3. 执行 `bash run.sh`。
4. 查看本目录 `summary.md` 与 `logs/`。

## 实现

### 当前验证口径

脚本直连 UDS 调用 `RPC_TIER_STATS`，根据返回 JSON 字段判定 `PASS`、`FAIL` 或 `SKIP`。

### 脚本入口

- `run.sh`
- `run.py`

输出文件写入当前 `functions/storage/FN-1/` 目录和 `logs/` 子目录。

## 命令

```bash
bash functions/storage/FN-1/run.sh
```

