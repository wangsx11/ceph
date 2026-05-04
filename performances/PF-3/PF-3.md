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

### QoS 实现说明

PF-3 测试的 QoS 不是在测试脚本里伪造出来的优先级差异，而是在 C++ 数据面中实现的两级优先级调度。压测工具 `nr_bench` 通过 `--prio=hi` 或 `--prio=lo` 标记请求类型，高优先级请求会发送为 `RPC_KV_PUT_HI`，低优先级请求会发送为 `RPC_KV_PUT_LO`。数据面收到请求后，在 `do_put` 路径中把这个优先级标记传给 `QosSched`。

数据面 QoS 的核心实现位于：

- `native_rdma/data_plane/qos/qos_sched.h`
- `native_rdma/data_plane/qos/qos_sched.cpp`
- `native_rdma/data_plane/main.cpp`

当前实现分为两部分。

第一，高低优先级使用不同的 RDMA QP 组。高优先级请求从高优先级 QP 组中轮询选择 QP，低优先级请求从低优先级 QP 组中轮询选择 QP。这样做的目的是减少高低优先级在同一批 QP 上互相抢占，避免低优先级流量把高优先级复制路径完全挤占。

第二，低优先级采用自适应 token bucket 保护。高优先级请求到达时，`QosSched::on_submit(true)` 会记录一个“近期高优先级压力窗口”。在这个窗口内，低优先级请求调用 `QosSched::on_submit(false)` 时需要消耗 token；如果 token 不足，低优先级请求会短暂等待。没有高优先级压力时，低优先级请求不被额外限速，可以正常使用数据面能力。

默认参数由数据面启动时设置：

- `lo_rate_limit_kops`：高优先级压力窗口内低优先级的保护速率，当前默认约为 `160 kops/s`。
- `hi_activity_window_us`：高优先级压力窗口长度，当前默认 `200000 us`。
- `lo_burst_ms`：低优先级 token bucket 突发窗口，当前默认 `50 ms`。

这些参数可以通过环境变量做实验性调整：

- `NR_LO_RATE_KOPS`
- `NR_QOS_HI_WINDOW_US`
- `NR_QOS_LO_BURST_MS`

PF-3 默认不主动设置这些 QoS 参数，而是使用数据面默认配置。这样测试结果反映的是数据面自身 QoS 策略，而不是测试脚本为了通过指标临时注入的限速参数。

在 PF-3 的正式轮次中，脚本同时启动两个 `nr_bench` 进程：一个持续提交高优先级 PUT，另一个持续提交低优先级 PUT。两个进程都通过 Unix Domain Socket 进入同一个 C++ 数据面，并要求 `REQUIRE_PEER=1`，即 PUT 必须经过远端 RDMA peer 复制路径。最终统计高低优先级在同一竞争窗口内的真实完成吞吐。

### 当前统计口径

- `hi_ops = 高优先级成功事件数 / 高优先级 measured_seconds`。
- `lo_ops = 低优先级成功事件数 / 低优先级 measured_seconds`。
- `gain_pct = (hi_ops - lo_ops) / lo_ops * 100%`。
- 统计 measured 窗口内的事件完成效率，不统计脚本启动、环境启动和 warmup。
- 失败事件、降级事件和未完成事件必须单独记录；当前验收要求高低优先级请求的失败数和降级数均为 0。

### 脚本入口

- Bash 入口：`performances/PF-3/run.sh`。
- Python 入口：`performances/PF-3/run.py`。
- 本次运行结果直接写入当前 `performances/PF-3/` 目录。

## 命令

```bash
cd performances/PF-3
bash run.sh
```
