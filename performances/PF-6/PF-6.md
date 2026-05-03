# PF-6 多级存储读写能力测试说明

## 功能点

- 性能点名称：多级存储读写能力。
- 来源指标：`docs/性能要求.md` 第 6 条。
- 现有参考脚本：`native_rdma/tests/performance/perf_06_tier_bw.sh`。
- 功能说明：验证多级存储或全闪存阵列路径下的数据写入和读取带宽。

## 指标要求

- 写入速率 `write_gbs >= 10GB/s`。
- 读取速率 `read_gbs >= 20GB/s`。
- 需要报告读命中率或有效响应字节比例。
- 运行前提：如使用 1MB payload 场景，数据面启动时必须设置足够大的 slab slot，避免短响应或 miss 导致吞吐被高估。

## 测试方案

- 启动数据面并确认目标存储路径、热层和冷层配置。
- 确认测试使用真实可读写路径；如不是全闪存阵列，需要在结果中标注环境差异。
- 执行写入 measured 轮次，统计真实成功写入字节数和 measured 时间。
- 执行读取 measured 轮次，统计真实成功读取字节数、miss 数、短响应字节数和 measured 时间。

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
   cd performances/PF-6
   NR_ASYNC_REPL=1 bash run.sh
   ```
4. 查看结果：读取当前目录下的 `summary.md`，读写原始统计固定写入当前目录。

## 实现

### 当前统计口径

- `write_gbs = 真实成功写入字节数 / measured_seconds / 1,000,000,000`。
- `read_gbs = 真实成功读取字节数 / measured_seconds / 1,000,000,000`。
- 读取吞吐必须使用真实响应字节计数，不能用 `ops/s * 假定对象大小` 估算。
- 读 miss、短响应、错误响应和降级路径必须单独记录。
- 不统计构建、脚本启动、环境启动、控制面页面操作、数据预生成和 warmup 时间。

### 脚本入口

- Bash 入口：`performances/PF-6/run.sh`。
- Python 入口：`performances/PF-6/run.py`。
- 本次运行结果直接写入当前 `performances/PF-6/` 目录。

## 命令

```bash
cd performances/PF-6
bash run.sh
```
