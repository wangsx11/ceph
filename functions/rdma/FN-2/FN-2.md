# FN-2 聚合数据传输测试说明

## 功能点

验证小对象批量传输路径、BatchAggregator 初始化证据，以及批量 RDMA 写入到 peer 后的远端读回闭环。

## 来源要求

`docs/功能要求.md` / RDMA 分布式仿真计算模块 / 第 2 条。

## 实现位置

- `native_rdma/data_plane/batch/batch_aggregator.cpp`
- `native_rdma/data_plane/main.cpp` 的 `RPC_KV_PUT_BATCH`
- `RPC_TCP_GET_PEER` 作为 peer 读回验证通道

## 完成判据

最近一次数据面启动日志包含 `BatchAggregator started`、RDMA QP 初始化和 `OOB exchanged`。

默认 `REQUIRE_PEER=1` 时，`peer_alive` 必须为 `true`；否则只能证明本地批量写入，不能证明 RDMA 聚合传输。

完整验收要求以默认 RDMA transport、`NR_ASYNC_REPL=0` 启动数据面。`RPC_KV_PUT_BATCH` 必须返回 `ok=true`，`ok_n` 与提交条数一致，`replicated_n` 与提交条数一致，`degraded_n=0`，`repl_failed_n=0`，`transport=rdma`。随后脚本用 `RPC_TCP_GET_PEER` 逐项从 xfusion4 读回相同 value，证明批量 RDMA 数据面写入和 peer 元数据闭环都成立。

注意：当前 `RPC_KV_PUT_BATCH` 是批量 RPC + 批量 slab/tier 处理 + 多个 RDMA WRITE 的数据面路径；`BatchAggregator` 线程会启动，但该 RPC 尚未接入 `BatchAggregator::submit()` 的 linked-list doorbell 聚合。因此 FN-2 可按“批量小对象 RDMA 传输闭环”展示，不应夸大为已经证明 doorbell batching 性能收益。

## 测试方案

前置条件：数据面 UDS 在线；xfusion4 peer 在线；建议同步复制模式启动。

当前验证口径：构造多个小对象的二进制 batch body，直接调用批量 PUT RPC；脚本先检查当前双节点状态和最近启动日志，再要求 batch 响应中的复制计数完整，最后通过 peer 读回校验所有对象内容。

不验证内容：不统计批处理吞吐、延迟或 doorbell 聚合收益；正式性能收益仍归入 `performances/`。

## 交互

1. 启动双节点数据面。
2. 执行 `bash functions/rdma/FN-2/run.sh`。
3. 查看 `summary.md`、`raw.json` 和过程日志。

## 实现

### 当前验证口径

脚本直接实现 `RPC_KV_PUT_BATCH` wire format，不依赖 `native_rdma/scripts/`。脚本只扫描最近一次 `native_rdma_dp starting` 之后的日志段，避免用历史 `BatchAggregator started` 制造 PASS。

### 脚本入口

- `run.sh`
- `run.py`

输出文件写入当前 `functions/rdma/FN-2/` 目录和 `logs/` 子目录。

## 命令

```bash
cd native_rdma
bash start.sh
cd ..
bash functions/rdma/FN-2/run.sh
```

可选增加批量对象数：

```bash
FN2_BATCH_ITEMS=32 bash functions/rdma/FN-2/run.sh
```
