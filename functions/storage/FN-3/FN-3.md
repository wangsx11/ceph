# FN-3 多策略预取机制测试说明

## 功能点

验证顺序访问、stride 与 Markov 相关的预取统计和预测接口可用。

## 来源要求

`docs/功能要求.md` / 多级异构的高效能存储模块 / 第 3 条。

## 实现位置

- `native_rdma/data_plane/storage/prefetcher.cpp`
- `RPC_PREFETCH_STATS`

## 完成判据

连续访问带数字后缀的 key 后，`RPC_PREFETCH_STATS` 返回 `ok=true`，`total_access` 增加，`predicted` 包含下一顺序 key。

## 测试方案

前置条件：数据面 UDS 在线。

当前验证口径：写入并顺序读取一组唯一 key，检查 stride 预测结果。

不验证内容：不证明预取带来的吞吐或延迟收益。

## 交互

1. 启动数据面。
2. 执行 `bash functions/storage/FN-3/run.sh`。
3. 查看 `summary.md` 和 `logs/` 中的原始 RPC 响应。

## 实现

### 当前验证口径

脚本通过 UDS 调用 `RPC_KV_PUT`、`RPC_KV_GET` 和 `RPC_PREFETCH_STATS`。

### 脚本入口

- `run.sh`
- `run.py`

输出文件写入当前 `functions/storage/FN-3/` 目录和 `logs/` 子目录。

## 命令

```bash
bash functions/storage/FN-3/run.sh
```

