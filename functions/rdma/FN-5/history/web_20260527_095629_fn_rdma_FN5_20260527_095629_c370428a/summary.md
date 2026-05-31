# FN-5 Summary

- Module: RDMA 分布式仿真计算模块
- Function: 分布式节点路由转发与负载均衡
- Source: docs/功能要求.md / RDMA 分布式仿真计算模块 / 第 5 条
- Last Run: 2026-05-27T09:56:29+0800
- Result: PASS
- Completion: 完成
- Log: /home/wangshouxin/native-rdma-web/functions/rdma/FN-5/history/web_20260527_095629_fn_rdma_FN5_20260527_095629_c370428a/logs/run_20260527_095629.log
- Raw: /home/wangshouxin/native-rdma-web/functions/rdma/FN-5/history/web_20260527_095629_fn_rdma_FN5_20260527_095629_c370428a/raw.json

## 关键证据

- 64 个 key 路由查询成功，primary 分布: {'192.168.0.218': 32, '192.168.0.214': 32}
- 本地 primary 写入未转发: key=fn_route_1779846989215_3431597_0 primary=192.168.0.218
- 远端 primary 写入已通过 RDMA 转发到 peer: key=fn_route_1779846989219_3431597_32 primary=192.168.0.214 offset=134221824 qp_idx=0
- 本地 GET 与 peer GET 均完成同值读回；replica 为空样本数=15

## 统计口径

- 验证路由查询和分布计数；replica 为空时记录为当前路由策略细节。
- 验证 remote-primary key 的 RDMA 跨节点转发闭环，不只做路由表展示。
- 不验证跨交换机或多级转发性能；RPC_TCP_GET_PEER 仅作为 peer 内容读回校验通道。
