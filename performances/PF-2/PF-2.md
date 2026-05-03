# PF-2 RDMA 网络环境下对象传输能力测试说明

## 功能点

- 性能点名称：RDMA 网络环境下对象传输能力。
- 来源指标：`docs/性能要求.md` 第 2 条。
- 现有参考脚本：`native_rdma/tests/performance/perf_02_latency.sh`。
- 功能说明：验证端到端传输 10 万个 1KB 仿真对象时的数据面对象传输时延。

## 指标要求

- 默认样本规模：至少 100,000 个 1KB 对象。
- 平均时延 `lat_avg_us <= 50us`。
- P99 响应时间 `lat_p99_us <= 100us`。
- 需要同时报告 P50、P99、P99.9、最大时延和成功样本数。

## 测试方案

- 启动双节点数据面并确认远端 peer 可用。
- 执行 warmup 轮次，丢弃 warmup 样本。
- 正式轮次中连续传输至少 100,000 个 1KB 对象，记录每个成功对象的端到端数据面时延。
- 对成功样本计算平均值、P50、P99、P99.9 和最大值，并记录失败样本数。
- 8 个线程跑满 10 秒
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
   export MEASURED_RUNS=100000
   ```
3. 执行脚本：
   ```bash
   cd performances/PF-2
   bash run.sh
   ```
4. 查看结果：读取当前目录下的 `summary.md`，原始样本可在后续实现中写入当前目录下的 `raw.csv` 或 `raw.json`。

## 实现

### 当前统计口径

- 时延口径为数据面热路径端到端时延，建议从对象发送提交点到完成确认点。
- 统计成功样本的平均值、P50、P99、P99.9 和最大值。
- 失败请求单独计数，不混入成功样本分位数。
- 不统计控制面 HTTP、脚本启动、环境启动、构建和 warmup 时间。

### 脚本入口

- Bash 入口：`performances/PF-2/run.sh`。
- Python 入口：`performances/PF-2/run.py`。
- 本次运行结果直接写入当前 `performances/PF-2/` 目录。

## 命令

```bash
cd performances/PF-2
bash run.sh
```
