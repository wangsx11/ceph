# FN-3 流量优先级机制测试说明

## 功能点

验证 QoS 调度器初始化，以及高低优先级数据路径均可提交。

## 来源要求

`docs/功能要求.md` / RDMA 分布式仿真计算模块 / 第 3 条。

## 实现位置

- `native_rdma/data_plane/qos/qos_sched.cpp`
- `RPC_KV_PUT_HI`
- `RPC_KV_PUT_LO`

## 完成判据

数据面日志包含 `QosSched ready`；`RPC_KV_PUT_HI` 与 `RPC_KV_PUT_LO` 均返回 `ok=true`。

## 测试方案

前置条件：数据面 UDS 在线；当前角色数据面日志可读。

当前验证口径：扫描 QoS 初始化日志，并分别执行高优先级与低优先级 PUT。

不验证内容：不验证 22% 效率提升，性能收益归入 `performances/PF-3`。

## 交互

1. 启动数据面。
2. 执行 `bash functions/rdma/FN-3/run.sh`。
3. 查看 `summary.md` 和 RPC 响应。

## 实现

### 当前验证口径

脚本调用 `RPC_KV_PUT_HI`、`RPC_KV_PUT_LO`，并读取 `QosSched ready` 日志。

### 脚本入口

- `run.sh`
- `run.py`

输出文件写入当前 `functions/rdma/FN-3/` 目录和 `logs/` 子目录。

## 命令

```bash
bash functions/rdma/FN-3/run.sh
```

