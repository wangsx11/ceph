# PF-8 RDMA 网络环境下仿真引擎运行能力测试说明

## 功能点

- 性能点名称：RDMA 网络环境下仿真引擎运行能力。
- 来源指标：`docs/性能要求.md` 第 8 条。
- 现有参考脚本：`native_rdma/tests/performance/perf_08_simulation.sh`。
- 功能说明：验证仿真引擎在大规模实体和事件负载下的实时推进能力。

## 指标要求

- 默认节点数：4 个。
- 默认实体数：100,000。
- 默认实体大小：1KB。
- 默认事件数：1,000,000。
- 仿真运行速度 `speedup >= 1.0`，即不低于 1 倍实时推进速度。

## 测试方案

- 启动仿真引擎和数据面依赖。
- 当前硬件事实是双节点，指标要求为 4 个节点；后续实现必须明确采用模拟 4 节点、扩展到真实 4 节点，还是按双节点降级演示。
- 执行 warmup 或轻量预运行，丢弃 warmup 统计。
- 正式运行 100,000 个实体和 1,000,000 个事件，记录仿真时间、墙钟时间、事件吞吐和 speedup。

## 交互

1. 启动环境：
   ```bash
   cd native_rdma
   bash start.sh
   ```
2. 设置可选参数：
   ```bash
   export CTRL_URL=http://127.0.0.1:5000
   export SIM_NODES=4
   export ENTITIES=100000
   export EVENTS=1000000
   ```
3. 执行脚本：
   ```bash
   # 需要先启动数据面
   cd native_rdma
   bash start.sh
   cd performances/PF-8
   bash run.sh
   ```
4. 查看结果：读取当前目录下的 `summary.md`，仿真原始输出固定写入当前目录。

## 实现

### 当前统计口径

- `speedup = simulated_seconds / wall_seconds`。
- `events_per_sec = completed_events / wall_seconds`。
- 统计 measured 仿真运行窗口，不统计构建、脚本启动、环境启动和 warmup 时间。
- 必须记录节点口径：真实 4 节点、模拟 4 节点或双节点降级。
- 失败事件、丢弃事件和未完成事件必须单独记录。

### 脚本入口

- Bash 入口：`performances/PF-8/run.sh`。
- Python 入口：`performances/PF-8/run.py`。
- 本次运行结果直接写入当前 `performances/PF-8/` 目录。

## 命令

```bash
cd performances/PF-8
bash run.sh
```
