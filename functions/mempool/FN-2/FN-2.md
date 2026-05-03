# FN-2 分布式内存池 API 测试说明

## 功能点

验证分布式内存池封装 API 的基本 PUT/GET 闭环。

## 来源要求

`docs/功能要求.md` / 一致性总线内存池化仿真计算模块 / 第 2 条。

## 实现位置

- `RPC_KV_PUT`
- `RPC_KV_GET`
- `PoolRegistry`

## 完成判据

写入唯一 key 后，`RPC_KV_GET` 返回 `ok=true` 且 `val` 与写入内容一致。

## 测试方案

前置条件：数据面 UDS 在线。

当前验证口径：直接走 UDS 数据面闭环，不只验证 Flask 控制面参数解析。

不验证内容：不验证性能指标或对象同步 UI。

## 交互

1. 启动数据面。
2. 执行 `bash functions/mempool/FN-2/run.sh`。
3. 查看 `summary.md`。

## 实现

### 当前验证口径

脚本调用 `RPC_KV_PUT` 和 `RPC_KV_GET`。

### 脚本入口

- `run.sh`
- `run.py`

输出文件写入当前 `functions/mempool/FN-2/` 目录和 `logs/` 子目录。

## 命令

```bash
bash functions/mempool/FN-2/run.sh
```

