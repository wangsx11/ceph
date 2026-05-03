# FN-5 IO 调度与优先级管理测试说明

## 功能点

验证前台 I/O 与后台 I/O 调度器初始化。

## 来源要求

`docs/功能要求.md` / 多级异构的高效能存储模块 / 第 5 条。

## 实现位置

- `native_rdma/data_plane/storage/io_scheduler.cpp`
- `native_rdma/logs/dp_<role>.log`

## 完成判据

当前数据面日志中存在 `IoScheduler init fg=... bg=...`。

## 测试方案

前置条件：数据面 UDS 在线；当前角色对应日志文件可读。

当前验证口径：调用 `RPC_CLUSTER_STATUS` 获取当前角色，再读取 `native_rdma/logs/dp_<role>.log` 查找初始化证据。

不验证内容：不统计优先级吞吐提升比例。

## 交互

1. 启动数据面。
2. 执行 `bash functions/storage/FN-5/run.sh`。
3. 查看日志证据路径。

## 实现

### 当前验证口径

脚本检查数据面日志中的 `IoScheduler init` 记录。

### 脚本入口

- `run.sh`
- `run.py`

输出文件写入当前 `functions/storage/FN-5/` 目录和 `logs/` 子目录。

## 命令

```bash
bash functions/storage/FN-5/run.sh
```

