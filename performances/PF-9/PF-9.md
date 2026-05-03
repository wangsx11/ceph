# PF-9 仿真引擎内存池化能力测试说明

## 功能点

- 性能点名称：仿真引擎内存池化能力。
- 来源指标：`docs/性能要求.md` 第 9 条。
- 现有参考脚本：`native_rdma/tests/performance/perf_09_mempool.sh`。
- 功能说明：验证内存池化在性能损失受控前提下的内存节省能力，以及单节点多线程分配释放吞吐提升。

## 指标要求

- 默认对象大小：1KB。
- 场景一：启用内存池后的性能损失 `overhead_pct <= 5%`，内存节省 `savings_pct >= 7%`。
- 场景二：单节点多线程高并发 1KB 对象分配/释放吞吐提升 `scale_gain_pct >= 20%`。
- 需要报告线程数、总操作数、基线吞吐、内存池吞吐、性能损失、内存节省和扩展收益。

## 测试方案

- 准备基线实现和内存池实现的可比测试路径。
- 执行 warmup 轮次，丢弃 warmup 统计。
- 场景一对比启用内存池前后的性能和内存占用。
- 场景二在单节点多线程下对比 1KB 对象分配/释放吞吐，计算吞吐提升比例。

## 交互

1. 构建数据面或单元 bench：
   ```bash
   cd native_rdma
   cmake --build build -j
   ```
2. 设置可选参数：
   ```bash
   export THREADS=8
   export OBJECT_SIZE=1024
   export MEASURED_RUNS=3
   ```
3. 执行脚本：
   ```bash
   cd performances/PF-9
   bash run.sh
   ```
4. 查看结果：读取当前目录下的 `summary.md`，原始对比数据固定写入当前目录。

## 实现

### 当前统计口径

- `overhead_pct = (pool_time - baseline_time) / baseline_time * 100%`。
- `savings_pct = (baseline_memory - pool_memory) / baseline_memory * 100%`。
- `scale_gain_pct = (pool_alloc_free_ops - baseline_alloc_free_ops) / baseline_alloc_free_ops * 100%`。
- 统计 measured 测试窗口，不统计构建、脚本启动、环境启动和 warmup 时间。
- 基线与内存池场景必须使用相同对象大小、线程数、操作数和硬件环境。

### 脚本入口

- Bash 入口：`performances/PF-9/run.sh`。
- Python 入口：`performances/PF-9/run.py`。
- 本次运行结果直接写入当前 `performances/PF-9/` 目录。

## 命令

```bash
cd performances/PF-9
bash run.sh
```
