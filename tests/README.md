# CEPH + RDMA 集群测试套件

本套件用于对基于 RDMA 底层部署的 CEPH 集群进行全面的功能与性能验证。

## 目录结构

```
tests/
├── functional/                       # 功能测试（按需求模块分三组）
│   ├── storage_heterogeneous/        # 多级异构高效能存储模块
│   ├── rdma_distributed/             # RDMA 分布式仿真计算模块
│   └── memory_pool/                  # 一致性总线内存池化模块
├── performance/                      # 性能测试（对照性能指标）
│   ├── baseline/                     # 基准测试
│   ├── stress/                       # 压力测试
│   └── rdma_network/                 # RDMA 网络性能
└── common/                           # 公共库（Ceph/RDMA 工具封装）
```

## 运行环境要求

| 项目 | 版本 / 规格 |
|------|-------------|
| 操作系统 | Linux (Ubuntu 22.04 / CentOS 8+) |
| Ceph | v18 (Reef) 或更高，已启用 `ms_type=async+rdma` |
| RDMA | InfiniBand / RoCE，`ibverbs` + `rdma_core` 已加载 |
| Python | 3.8+ (`rados`, `rbd`, `numpy`, `pyverbs` 可选) |
| 工具链 | `ib_send_bw`, `ib_write_bw`, `ib_read_lat`, `perftest`, `fio`, `rados bench` |
| 节点数 | ≥ 3 节点集群（演示验证 ≥ 2 节点） |

## 一键执行

```bash
# 全部功能测试
bash tests/run_all_functional.sh

# 全部性能测试（耗时较长）
bash tests/run_all_performance.sh

# 指定模块
bash tests/functional/rdma_distributed/run.sh
bash tests/performance/rdma_network/run.sh
```

## 退出码规范

| 码 | 含义 |
|----|------|
| 0 | 通过 |
| 1 | 断言失败 / 指标未达标 |
| 2 | 环境缺失（ibverbs/rados 不可用等） |
| 3 | 执行期间异常 |

所有脚本遵循 "**失败即 exit 非 0**" 原则，便于 CI 流水线集成。
