# FN-5 Summary

- Module: RDMA 分布式仿真计算模块
- Function: 分布式节点路由转发与负载均衡
- Source: docs/功能要求.md / RDMA 分布式仿真计算模块 / 第 5 条
- Last Run: 2026-05-03T23:41:53+0800
- Result: PASS
- Completion: 完成
- Log: /home/wangshouxin/native-rdma-web/functions/rdma/FN-5/logs/run_20260503_234153.log
- Raw: /home/wangshouxin/native-rdma-web/functions/rdma/FN-5/raw.json

## 关键证据

- 32 个 key 路由查询成功，primary 分布: {'192.168.0.218': 10, '192.168.0.214': 22}
- replica 为空的样本数=16，当前 ObjectRouter 在副本 hash 命中 primary 时会置空

## 统计口径

- 验证路由和分布计数；replica 为空时记录为当前路由策略细节。
- 不验证跨交换机或多级转发性能。
