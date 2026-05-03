# PF-3 RDMA 网络环境下 QoS 事件优先级传输能力测试说明

## 功能点

- 性能点名称：RDMA 网络环境下 QoS 事件优先级传输能力。
- 来源指标：`docs/性能要求.md` 第 3 条。
- 现有参考脚本：`native_rdma/tests/performance/perf_03_qos.sh`。
- 功能说明：验证 QoS 调度在高低优先级事件混合输入时，对高优先级事件提供更高处理效率。

## 指标要求

- 默认事件规模：高优先级事件 2500 个，低优先级事件 2500 个。
- 高优先级相对低优先级处理效率提升 `gain_pct >= 22%`。
- 提升比例公式：`gain_pct = (hi_ops - lo_ops) / lo_ops * 100%`。

## 测试方案

- 启动数据面并确认 QoS 调度路径启用。
- 执行 warmup 轮次，丢弃 warmup 统计。
- 正式轮次中提交相同数量的高优先级和低优先级事件。
- 分别统计高优先级事件和低优先级事件的完成吞吐，计算提升比例。

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
   export HI_EVENTS=2500
   export LO_EVENTS=2500
   ```
3. 执行脚本：
   ```bash
   cd performances/PF-3
   NR_ASYNC_REPL=1 bash run.sh
   ```
4. 查看结果：读取当前目录下的 `summary.md`，后续实现生成的原始事件统计固定写入当前目录。

## 实现

### 当前统计口径

- `hi_ops = 高优先级成功事件数 / 高优先级 measured_seconds`。
- `lo_ops = 低优先级成功事件数 / 低优先级 measured_seconds`。
- `gain_pct = (hi_ops - lo_ops) / lo_ops * 100%`。
- 统计 measured 窗口内的事件完成效率，不统计脚本启动、环境启动和 warmup。
- 失败事件、降级事件和未完成事件必须单独记录。

### 脚本入口

- Bash 入口：`performances/PF-3/run.sh`。
- Python 入口：`performances/PF-3/run.py`。
- 本次运行结果直接写入当前 `performances/PF-3/` 目录。

## 命令

```bash
cd performances/PF-3
bash run.sh
```
