# FN-6 仿真数据运行中采集测试说明

## 功能点

验证仿真运行期间对象属性、交互事件等数据流能够进入采集缓冲和 WAL。

## 来源要求

`docs/功能要求.md` / 多级异构的高效能存储模块 / 第 6 条。

## 实现位置

- `native_rdma/data_plane/sim/sim_engine.cpp`
- `native_rdma/data_plane/sim/sim_capture.cpp`
- `RPC_SIM_RUN`
- `RPC_SIM_CAPTURE_STATS`

## 完成判据

`RPC_SIM_RUN` 返回 `ok=true` 且 `captured_events>0`；随后 `RPC_SIM_CAPTURE_STATS` 返回 `pushed_events>0`、`flushed_events>0`。

## 测试方案

前置条件：数据面 UDS 在线。

当前验证口径：重置采集计数，运行轻量仿真，等待后台 flush 后读取采集统计。

不验证内容：不统计仿真加速比或事件吞吐性能。

## 交互

1. 启动数据面。
2. 执行 `bash functions/storage/FN-6/run.sh`。
3. 查看 `summary.md`、`raw.json` 与 `logs/`。

## 实现

### 当前验证口径

脚本调用 `RPC_SIM_CAPTURE_RESET`、`RPC_SIM_RUN` 和 `RPC_SIM_CAPTURE_STATS`。

### 脚本入口

- `run.sh`
- `run.py`

输出文件写入当前 `functions/storage/FN-6/` 目录和 `logs/` 子目录。

## 命令

```bash
bash functions/storage/FN-6/run.sh
```

