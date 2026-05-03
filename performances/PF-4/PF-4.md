# PF-4 RDMA 网络环境下对象数据聚合传输能力测试说明

## 功能点

- 性能点名称：RDMA 网络环境下对象数据聚合传输能力。
- 来源指标：`docs/性能要求.md` 第 4 条。
- 现有参考脚本：`native_rdma/tests/performance/perf_04_batch_latency.sh`。
- 功能说明：验证对象聚合批量传输在固定批次数下的总耗时。

## 指标要求

- 场景 A：100 个 1KB 对象，1000 批次，总耗时 `<= 200ms`。
- 场景 B：1000 个 1KB 对象，100 批次，总耗时 `<= 100ms`。
- 不同批次之间串行执行，前一批次完成后再发送下一批次。

## 测试方案

- 启动双节点数据面并确认批处理聚合路径可用。
- 执行 warmup 轮次，丢弃 warmup 统计。
- 场景 A 和场景 B 分别执行，记录每个场景从第一批提交到最后一批完成确认的总耗时。
- 记录成功批次数、失败批次数、降级批次数和每个场景的总传输对象数。

## 交互

1. 启动环境：
   ```bash
   cd native_rdma
   NR_ASYNC_REPL=1 bash start.sh
   ```
2. 设置可选参数：
   ```bash
   export UDS=/tmp/native_rdma-dp.sock
   export CTRL_URL=http://127.0.0.1:5000
   export REQUIRE_PEER=1
   ```
3. 执行脚本：
   ```bash
   cd performances/PF-4
   bash run.sh
   ```
4. 查看结果：读取当前目录下的 `summary.md`，场景明细固定写入当前目录。

## 实现

### 当前统计口径

- 场景 A 总耗时：1000 个串行批次，每批 100 个 1KB 对象。
- 场景 B 总耗时：100 个串行批次，每批 1000 个 1KB 对象。
- 计时从场景第一批提交开始，到该场景最后一批完成确认结束。
- 不统计构建、脚本启动、环境启动、控制面页面操作和 warmup 时间。
- 失败批次和降级批次必须单独记录，不能计入成功批次。

### 脚本入口

- Bash 入口：`performances/PF-4/run.sh`。
- Python 入口：`performances/PF-4/run.py`。
- 本次运行结果直接写入当前 `performances/PF-4/` 目录。

## 命令

```bash
cd performances/PF-4
bash run.sh
```
