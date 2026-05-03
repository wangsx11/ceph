# FN-4 跨节点内存自适应分配与热数据迁移测试说明

## 功能点

验证当前实现中可观测的本地热数据迁移闭环，并明确与完整跨节点远端内存自适应放置的边界。

## 来源要求

`docs/功能要求.md` / 一致性总线内存池化仿真计算模块 / 第 4 条。

## 实现位置

- `TierEngine`
- `RPC_TIER_DEMOTE`
- `RPC_KV_GET`
- `native_rdma/logs/dp_<role>.log`

## 完成判据

日志包含 `TierEngine init`；对象 demote 到 `nvme` 后，读取返回 `nvme_promote` 或同等提升证据。

## 测试方案

前置条件：数据面 UDS 在线；当前角色数据面日志可读。

当前验证口径：验证现有可观测迁移路径，结果的完成情况标记为“部分完成”。

不验证内容：不把存储层迁移等同为完整跨节点 RDMA 远端/本地内存自适应放置。

## 交互

1. 启动数据面。
2. 执行 `bash functions/mempool/FN-4/run.sh`。
3. 查看 `summary.md` 中的完成情况说明。

## 实现

### 当前验证口径

脚本写入对象、demote 到 NVMe、读取触发提升，并扫描 `TierEngine init` 日志。

### 脚本入口

- `run.sh`
- `run.py`

输出文件写入当前 `functions/mempool/FN-4/` 目录和 `logs/` 子目录。

## 命令

```bash
bash functions/mempool/FN-4/run.sh
```

