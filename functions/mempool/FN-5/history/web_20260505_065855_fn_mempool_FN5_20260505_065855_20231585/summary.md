# FN-5 Summary

- Module: 一致性总线内存池化仿真计算模块
- Function: 任务级与用户级内存隔离
- Source: docs/功能要求.md / 一致性总线内存池化仿真计算模块 / 第 5 条
- Last Run: 2026-05-05T06:58:55+0800
- Result: PASS
- Completion: 完成
- Log: /home/wangshouxin/native-rdma-web/functions/mempool/FN-5/history/web_20260505_065855_fn_mempool_FN5_20260505_065855_20231585/logs/run_20260505_065855.log
- Raw: /home/wangshouxin/native-rdma-web/functions/mempool/FN-5/history/web_20260505_065855_fn_mempool_FN5_20260505_065855_20231585/raw.json

## 关键证据

- tenant=36535 完成拒绝->允许->读取->撤销->拒绝闭环
- tenant=36535 与 tenant=136535 使用同一逻辑 key 时读回各自 value，证明命名空间隔离
- RPC_ISO_LIST 证明 ACL 授权/撤销状态生效: 36535|default/slab1k allow 后存在，最终撤销后不存在

## 统计口径

- 验证任务级/用户级 ACL 生效和非默认 tenant 内部 key 命名空间隔离。
- 使用临时 tenant id，避免污染默认租户。
- 不验证 Linux 进程 UID/GID 或硬件 PD/MR 级隔离。
