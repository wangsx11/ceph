# FN-5 IO 调度与优先级管理测试说明

## 功能点

验证前台 I/O 与后台 I/O 调度器初始化，并验证 NVMe/HDD 数据路径分别产生前台/后台 I/O 计数。

## 来源要求

`docs/功能要求.md` / 多级异构的高效能存储模块 / 第 5 条。

## 实现位置

- `native_rdma/data_plane/storage/io_scheduler.cpp`
- `native_rdma/logs/dp_<role>.log`
- `RPC_IO_STATS`
- `RPC_TIER_DEMOTE`
- `RPC_KV_GET`

## 完成判据

同时满足：

1. 当前数据面日志中存在 `IoScheduler init fg=... bg=...`；
2. NVMe 探针对象执行 `PUT -> RPC_TIER_DEMOTE(nvme) -> GET` 后，`RPC_IO_STATS` 中 `fg_write_ops` 和 `fg_read_ops` 增加；
3. HDD 探针对象执行 `PUT -> RPC_TIER_DEMOTE(hdd) -> GET` 后，`RPC_IO_STATS` 中 `bg_write_ops` 和 `bg_read_ops` 增加；
4. 两个探针对象均能通过 `RPC_KV_GET` 读回原始内容。

## 测试方案

前置条件：数据面 UDS 在线；当前角色对应日志文件可读。

当前验证口径：调用 `RPC_CLUSTER_STATUS` 获取当前角色，读取 `native_rdma/logs/dp_<role>.log` 查找初始化证据；随后通过 `RPC_IO_STATS` 读取计数基线，构造 NVMe 前台路径和 HDD 后台路径，检查对应读写计数增加。

不验证内容：不统计优先级吞吐提升比例。

## 交互

1. 启动数据面。
2. 执行 `bash functions/storage/FN-5/run.sh`。
3. 查看日志证据路径。

## 实现

### 当前验证口径

脚本检查数据面日志中的 `IoScheduler init` 记录，并通过真实对象 demote/get 触发前台和后台 I/O。

### 脚本入口

- `run.sh`
- `run.py`

输出文件写入当前 `functions/storage/FN-5/` 目录和 `logs/` 子目录。

## 命令

```bash
bash functions/storage/FN-5/run.sh
```
