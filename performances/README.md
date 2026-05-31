# performances 使用说明

本目录是 9 个性能指标的独立测试入口。每个 `PF-N/` 都可以单独执行，结果写回本目录。

## 在执行测试前首先需要启动数据面

这里的“数据面”指 `native_rdma/build/bin/native_rdma_dp` 这个 C++ 进程。

PF-1 到 PF-6、PF-8 会通过 Unix domain socket 访问数据面，默认路径是：

```bash
/tmp/native_rdma-dp.sock
```

因此“数据面已启动”至少意味着：

```bash
test -S /tmp/native_rdma-dp.sock
```

在当前运行测试的节点上返回成功。由于默认 `REQUIRE_PEER=1`，PF-1 到 PF-6 还要求双节点 RDMA peer 正常连接，避免本地降级结果污染验收。

## 启动数据面

推荐在节点 A `xfusion3` 上一键启动双节点：

```bash
cd native_rdma
bash start.sh
```

该脚本会构建本地和远端、停止旧进程、先启动节点 B，再启动节点 A。启动完成后在节点 A 上检查：

```bash
test -S /tmp/native_rdma-dp.sock
```

也可以手动启动。先在节点 B：

```bash
cd ~/ceph-web/native_rdma
ROLE=B bash scripts/demo_up.sh
```

再在节点 A：

```bash
cd ~/ceph-web/native_rdma
ROLE=A bash scripts/demo_up.sh
```

停止：

```bash
cd native_rdma
bash scripts/demo_down.sh
```

## PF-6 的特殊启动参数

PF-6 使用默认 1MB payload 验证读写带宽。数据面默认 slab slot 是 4KB，不足以接受 1MB 对象。跑 PF-6 前需要用更大的 slot 重启两端数据面。

节点 B：

```bash
cd ~/ceph-web/native_rdma
ROLE=B SLAB_SLOT_SIZE=1048576 SLAB_TOTAL_BYTES=4294967296 bash scripts/demo_up.sh
```

节点 A：

```bash
cd ~/ceph-web/native_rdma
ROLE=A SLAB_SLOT_SIZE=1048576 SLAB_TOTAL_BYTES=4294967296 bash scripts/demo_up.sh
```

## 目录和文件

每个性能点目录结构相同：

```text
PF-N/
├── PF-N.md       # 该性能点的测试要求、指标阈值、测试口径和交互说明
├── run.sh        # Bash 入口，只做目录定位、环境变量默认值和调用 run.py
├── run.py        # 该性能点的实际测试逻辑
└── summary.md    # 最近一次运行的人类可读汇总结果，每次运行会覆盖
```

运行后还会生成：

```text
raw.json          # 最近一次运行的机器可读结果，每次运行会覆盖
run.log           # 最近一次运行的命令和原始输出，每次运行会覆盖
perf_*.json       # 按时间戳保存的单次结果快照
```

根目录文件：

```text
run_all.sh        # 批量执行 PF-1 到 PF-9
run_all.py        # 批量执行和总览 summary.md 生成逻辑
summary.md        # 批量执行后的总览结果
```

## 单项测试方式

通用命令：

```bash
cd performances/PF-N
bash run.sh
```

每次运行后查看：

```bash
cat summary.md
```

## 批量测试方式

```bash
cd performances
bash run_all.sh
```

批量执行会依次运行 `PF-1` 到 `PF-9`，并生成：

```text
performances/summary.md
```

注意：PF-6 对数据面 slab 参数有特殊要求。如果直接批量执行且数据面按默认参数启动，PF-6 可能失败。严格验收时建议先按普通参数跑 PF-1 到 PF-5、PF-8，再按 PF-6 参数重启数据面单独跑 PF-6。

## 演示安全汇总方式

现场演示不建议从浏览器触发完整 `run_all.sh`。性能控制台的“运行演示性能流”会使用 presentation profile，仅复制既有 PF 证据到新的 web_all 历史目录并生成汇总，不启动长时间或高网络压力压测。该模式用于稳定展示结果材料和证据路径。

完整验收仍以 `bash performances/run_all.sh` 为准；presentation profile 不替代完整验收，不应作为新的性能达标结论。

## 每个性能点怎么测

| 性能点 | 是否需要数据面 | 主要依赖 | 执行命令 | 说明 |
|---|---|---|---|---|
| PF-1 RDMA 分布式通讯能力 | 是 | `native_rdma/build/bin/nr_bench` | `cd performances/PF-1 && bash run.sh` | 1KB PUT，线程数 8/16/24/32 扫描，取最佳吞吐。 |
| PF-2 对象传输时延 | 是 | `native_rdma/build/bin/nr_bench` | `cd performances/PF-2 && bash run.sh` | 1KB mixed workload，统计 avg/P50/P99/P99.9/max。 |
| PF-3 QoS 优先级 | 是 | `native_rdma/build/bin/nr_bench` | `cd performances/PF-3 && bash run.sh` | 高、低优先级并发压测，计算 `(hi - lo) / lo * 100%`。 |
| PF-4 对象聚合传输 | 是 | `native_rdma/build/bin/nr_bench` | `cd performances/PF-4 && bash run.sh` | 通过 measured ops/s 折算两个批处理场景总耗时。 |
| PF-5 批处理吞吐 | 是 | `native_rdma/build/bin/nr_bench` | `cd performances/PF-5 && bash run.sh` | 1KB PUT，计算 `MB/s = ops/s * val_size / 1e6`。 |
| PF-6 多级存储读写 | 是，且需要 1MB slab | `native_rdma/build/bin/nr_bench` | `cd performances/PF-6 && bash run.sh` | 使用真实请求/响应字节计数计算写入和读取 GB/s。 |
| PF-7 定期备份存储 | dataplane 后端需要数据面，fio 后端不需要 | 数据面 `RPC_BACKUP_WRITE` 或 `fio` | `cd performances/PF-7 && bash run.sh` | 4KB 写 P999；`passed=true` 只代表自动化延迟子项通过，严格 3+1 RAID5 验收需 `RAID5_CONFIRMED=1` 且 `strict_acceptance_passed=true`。 |
| PF-8 仿真引擎运行 | 是 | 数据面 UDS `RPC_SIM_RUN` | `cd performances/PF-8 && bash run.sh` | 通过 UDS 调用仿真 RPC，统计 speedup 和 events/s。 |
| PF-9 内存池化能力 | 否 | `native_rdma/build/bin/nr_mempool_bench` | `cd performances/PF-9 && bash run.sh` | 执行独立 C++ bench，输出 overhead/savings/scale。 |

## 常用环境变量

```bash
export UDS=/tmp/native_rdma-dp.sock
export REQUIRE_PEER=1
export DUR=10
export THREADS=8
```

PF-1 额外支持：

```bash
export LINK_GBPS=100
```

PF-6 额外支持：

```bash
export VAL_SIZE=1048576
export KEYSPACE=512
export PUT_THREADS=16
export GET_THREADS=8
```

PF-7 额外支持：

```bash
export BACKUP_TEST_PATH=/path/on/raid5
export RAID5_CONFIRMED=1
export DUR=60
export QUEUE_DEPTH=1
export THREADS=1
```

PF-7 结果字段中，`passed` 表示延迟测试本身通过；`strict_acceptance_passed`
同时要求延迟通过且 `RAID5_CONFIRMED=1`。Round 5 最终验收应检查后者，
避免把未确认 RAID5 拓扑的低延迟数据面路径误记为严格通过。

PF-8 额外支持：

```bash
export SIM_NODES=4
export ENTITIES=100000
export EVENTS=1000000
export STEP_US=10
export STRESS=32
```

## 构建依赖

如果 `nr_bench` 或 `nr_mempool_bench` 不存在，先构建：

```bash
cd native_rdma
cmake --build build -j
```

如果 build 目录还不存在：

```bash
cd native_rdma
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build -j
```
