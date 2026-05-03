# PF-1 RDMA 网络环境分布式通讯能力测试说明

## 功能点

- 性能点名称：RDMA 网络环境分布式通讯能力。
- 来源指标：`docs/性能要求.md` 第 1 条。
- 现有参考脚本：`native_rdma/tests/performance/perf_01_ops_1kb.sh`。
- 功能说明：验证双节点 RoCEv2 环境下数据面跨节点通信能力，包括 1KB 小对象吞吐和大对象 RDMA 网络带宽利用率。

## 指标要求

- 1KB 对象场景：吞吐量 `ops_per_sec >= 1,000,000 ops/s`。
- 大对象带宽场景：分布式带宽利用率 `util_pct >= 50%`。

## 测试方案

- 启动节点 A 和节点 B 的 native RDMA 数据面，确认跨节点 peer 连接可用。
- 先执行 warmup 轮次，使连接、内存池和路由进入稳定状态。
- 正式统计分为两个场景：
  - 1KB 小对象吞吐场景，统计成功完成的对象操作数和 measured 时间。
  - 大对象带宽场景，统计数据面 shared-memory metrics 中的 `bw_tx_gbps`，即 RDMA peer 复制路径上的网络发送带宽。
- 如 `REQUIRE_PEER=1`，必须确认请求经过远端节点或 RDMA peer，不能使用本地降级路径作为通过结果。

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
   cd performances/PF-1
   bash run.sh
   ```
4. 查看结果：读取当前目录下的 `summary.md`，如后续实现生成 `raw.json` 或 `raw.csv`，也固定写入当前目录。

## 实现

### 当前统计口径

- `ops_per_sec = 成功对象操作数 / measured_seconds`。
- `network_bw = measured 窗口内数据面 metrics.bw_tx_gbps 的平均值`。
- `util_pct = network_bw / 理论链路带宽 * 100%`。
- 统计 measured 测试窗口内的数据面热路径时间。
- 不统计构建时间、脚本启动时间、控制面页面操作时间、环境启动时间和 warmup 时间。
- `req_bytes` 只作为客户端请求字节辅助数据，不用于网络带宽利用率判定。
- 失败请求和降级请求必须单独记录，不能计入通过结果；任一子项 `ops_fail > 0` 或 `ops_degraded > 0` 均 FAIL。

### 脚本入口

- Bash 入口：`performances/PF-1/run.sh`。
- Python 入口：`performances/PF-1/run.py`。
- 本次运行结果直接写入当前 `performances/PF-1/` 目录。

## 命令

```bash
cd performances/PF-1
bash run.sh
```
