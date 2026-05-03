# FN-5 任务级与用户级内存隔离测试说明

## 功能点

验证不同租户对默认内存池的授权、撤销和访问隔离行为。

## 来源要求

`docs/功能要求.md` / 一致性总线内存池化仿真计算模块 / 第 5 条。

## 实现位置

- `native_rdma/data_plane/mempool/isolation.cpp`
- `RPC_ISO_ALLOW`
- `RPC_ISO_DENY`
- `RPC_KV_PUT`
- `RPC_KV_GET`

## 完成判据

临时 tenant 完成未授权写入失败、授权后写入成功、授权后读取成功、撤销后写入再次失败。

## 测试方案

前置条件：数据面 UDS 在线。

当前验证口径：使用临时 tenant id，执行拒绝、允许、读取、撤销、拒绝闭环。

不验证内容：不验证跨进程用户身份系统，只验证数据面 ACL。

## 交互

1. 启动数据面。
2. 执行 `bash functions/mempool/FN-5/run.sh`。
3. 查看 ACL RPC 原始响应。

## 实现

### 当前验证口径

脚本调用 `RPC_ISO_DENY`、`RPC_ISO_ALLOW` 和带 `T<tenant>:` 前缀的 KV RPC。

### 脚本入口

- `run.sh`
- `run.py`

输出文件写入当前 `functions/mempool/FN-5/` 目录和 `logs/` 子目录。

## 命令

```bash
bash functions/mempool/FN-5/run.sh
```

