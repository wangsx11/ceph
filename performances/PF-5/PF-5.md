# PF-5 RDMA 网络环境下批处理能力测试说明

## 功能点

- 性能点名称：RDMA 网络环境下批处理能力。
- 来源指标：`docs/性能要求.md` 第 5 条。
- 现有参考脚本：`native_rdma/tests/performance/perf_05_batch_bw.sh`。
- 功能说明：验证仿真引擎 1KB 对象批处理传输的业务载荷吞吐能力。

## 指标要求

- 默认对象大小：1KB。
- 默认覆盖 1000 批次和 100 批次两类场景。
- 批处理传输速度 `mb_per_sec >= 700MB/s`。
- 需要报告 `MB/s`、`ops/s`、失败数和降级数。

## 测试方案

- 启动双节点数据面并确认批处理路径可用。
- 执行 warmup 轮次，丢弃 warmup 统计。
- 分别执行 1000 批次和 100 批次场景，统计成功传输对象数、成功业务载荷字节数和 measured 时间。
- 按两个场景输出吞吐明细，并给出用于验收的关键吞吐值。

## 交互

1. 启动环境：
   ```bash
   cd native_rdma
   bash start.sh
   ```
2. 设置可选参数：
   ```bash
   export UDS=/tmp/native_rdma-dp.sock
   export CTRL_URL=http://127.0.0.1:5000
   export REQUIRE_PEER=1
   ```
3. 执行脚本：
   ```bash
   cd performances/PF-5
   NR_ASYNC_REPL=1 bash run.sh
   ```
4. 查看结果：读取当前目录下的 `summary.md`，原始场景输出固定写入当前目录。

## 实现

### 当前统计口径

- `mb_per_sec = 成功业务载荷字节数 / measured_seconds / 1,000,000`。
- `ops_per_sec = 成功对象数 / measured_seconds`。
- 统计 measured 窗口内的批处理数据面传输时间。
- 不统计构建、脚本启动、环境启动、控制面页面操作和 warmup 时间。
- 失败请求、降级请求和 fallback 请求必须单独记录。

### 脚本入口

- Bash 入口：`performances/PF-5/run.sh`。
- Python 入口：`performances/PF-5/run.py`。
- 本次运行结果直接写入当前 `performances/PF-5/` 目录。

## 命令

```bash
cd performances/PF-5
bash run.sh
```
