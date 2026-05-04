# FN-5 任务级与用户级内存隔离测试说明

## 功能点

验证不同租户对默认内存池的授权、撤销和访问隔离行为，并验证不同租户使用同一逻辑 key 时具有独立命名空间。

## 来源要求

`docs/功能要求.md` / 一致性总线内存池化仿真计算模块 / 第 5 条。

## 实现位置

- `native_rdma/data_plane/mempool/isolation.cpp`
- `native_rdma/data_plane/main.cpp` 的 `tenant_storage_key`：非默认 tenant 使用内部 key 前缀，避免不同 tenant 同名 key 串读或覆盖。
- `RPC_ISO_ALLOW`
- `RPC_ISO_DENY`
- `RPC_ISO_LIST`
- `RPC_KV_PUT`
- `RPC_KV_GET`

## 完成判据

1. 两个临时 tenant 初始未授权写入均失败。
2. tenant A 授权后写入同一逻辑 key 成功，并能读回 A 的 value。
3. tenant B 未授权时不能读取或写入该逻辑 key。
4. tenant B 授权后，在同一逻辑 key 写入 B 的 value，并且 tenant A 与 tenant B 读回各自 value，证明命名空间隔离。
5. 撤销 tenant A 后，tenant A 读取/写入失败，tenant B 仍可读回自己的 value。
6. 撤销 tenant B 后，tenant B 写入失败。
7. `RPC_ISO_LIST` 能反映 ACL 授权和撤销状态变化。

## 测试方案

前置条件：数据面 UDS 在线。

当前验证口径：使用两个临时 tenant id，执行拒绝、允许、同名 key 双租户写入/读取、撤销、拒绝闭环。

不验证内容：不验证 Linux 进程 UID/GID 或硬件 PD/MR 级隔离，只验证 C++ 数据面的 tenant/pool ACL 与 tenant key 命名空间隔离。

## 交互

1. 启动数据面。
2. 执行 `bash functions/mempool/FN-5/run.sh`。
3. 查看 ACL RPC 原始响应。

## 实现

### 当前验证口径

脚本调用 `RPC_ISO_DENY`、`RPC_ISO_ALLOW`、`RPC_ISO_LIST` 和带 `T<tenant>:` 前缀的 KV RPC。写入时使用同一个逻辑 key，要求两个 tenant 读回不同 value，防止只验证 ACL 而遗漏共享 key 空间串读问题。

### 脚本入口

- `run.sh`
- `run.py`

输出文件写入当前 `functions/mempool/FN-5/` 目录和 `logs/` 子目录。

## 命令

```bash
bash functions/mempool/FN-5/run.sh
```
