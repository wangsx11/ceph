# FN-5 Summary

- Module: RDMA 分布式仿真计算模块
- Function: 分布式节点路由转发与负载均衡
- Source: docs/功能要求.md / RDMA 分布式仿真计算模块 / 第 5 条
- Last Run: 2026-05-27T09:56:10+0800
- Result: FAIL
- Completion: 未完成
- Log: /home/wangshouxin/native-rdma-web/functions/rdma/FN-5/history/web_20260527_095610_fn_rdma_FN5_20260527_095610_b2cf8508/logs/run_20260527_095610.log
- Raw: /home/wangshouxin/native-rdma-web/functions/rdma/FN-5/history/web_20260527_095610_fn_rdma_FN5_20260527_095610_b2cf8508/raw.json

## 关键证据

- 远端 primary route PUT 后 peer GET 读回失败

## 统计口径

- 验证路由查询和分布计数；replica 为空时记录为当前路由策略细节。
- 验证 remote-primary key 的 RDMA 跨节点转发闭环，不只做路由表展示。
- 不验证跨交换机或多级转发性能；RPC_TCP_GET_PEER 仅作为 peer 内容读回校验通道。
