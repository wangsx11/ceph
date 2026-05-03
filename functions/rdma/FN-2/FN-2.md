# FN-2 聚合数据传输测试说明

## 功能点

验证小对象批量传输路径和 BatchAggregator 初始化证据。

## 来源要求

`docs/功能要求.md` / RDMA 分布式仿真计算模块 / 第 2 条。

## 实现位置

- `native_rdma/data_plane/batch/batch_aggregator.cpp`
- `RPC_KV_PUT_BATCH`

## 完成判据

`RPC_KV_PUT_BATCH` 返回 `ok=true`，且 `ok_n` 等于提交条数。

## 测试方案

前置条件：数据面 UDS 在线。

当前验证口径：构造多个小对象的二进制 batch body，直接调用批量 PUT RPC。

不验证内容：不统计批处理吞吐、延迟或聚合收益。

## 交互

1. 启动数据面。
2. 执行 `bash functions/rdma/FN-2/run.sh`。
3. 查看批量 RPC 原始响应。

## 实现

### 当前验证口径

脚本直接实现 `RPC_KV_PUT_BATCH` wire format，不依赖 `native_rdma/scripts/`。

### 脚本入口

- `run.sh`
- `run.py`

输出文件写入当前 `functions/rdma/FN-2/` 目录和 `logs/` 子目录。

## 命令

```bash
bash functions/rdma/FN-2/run.sh
```

