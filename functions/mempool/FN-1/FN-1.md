# FN-1 RDMA 语义远程内存访问与零拷贝测试说明

## 功能点

验证对象 PUT 走用户态 slab 与 RDMA WRITE 复制路径，并返回复制时延证据。

## 来源要求

`docs/功能要求.md` / 一致性总线内存池化仿真计算模块 / 第 1 条。

## 实现位置

- `RPC_KV_PUT`
- `RdmaCore::post_write`
- `SlabPool`
- `RPC_CLUSTER_STATUS`

## 完成判据

默认 `REQUIRE_PEER=1` 时，peer 在线；`RPC_KV_PUT` 返回 `ok=true`、`degraded=false`，并包含 `repl_ns`。

## 测试方案

前置条件：数据面 UDS 在线；默认需要 peer 在线，可用 `REQUIRE_PEER=0` 放宽。

当前验证口径：以 peer slab 元数据、PUT offset、`repl_ns`、`degraded=false` 作为当前可观测的 RDMA 语义远程写证据。

不验证内容：不从硬件计数器证明全链路零拷贝。

## 交互

1. 启动双节点数据面。
2. 执行 `bash functions/mempool/FN-1/run.sh`。
3. 查看 `summary.md` 与 `raw.json`。

## 实现

### 当前验证口径

脚本调用 `RPC_CLUSTER_STATUS` 和 `RPC_KV_PUT`。

### 脚本入口

- `run.sh`
- `run.py`

输出文件写入当前 `functions/mempool/FN-1/` 目录和 `logs/` 子目录。

## 命令

```bash
bash functions/mempool/FN-1/run.sh
```

