# FN-5 Summary

- Module: RDMA 分布式仿真计算模块
- Function: 分布式节点路由转发与负载均衡
- Source: docs/功能要求.md / RDMA 分布式仿真计算模块 / 第 5 条
- Last Run: 2026-05-05T06:55:31+0800
- Result: PASS
- Completion: 完成
- Log: /home/wangshouxin/native-rdma-web/functions/rdma/FN-5/history/web_20260505_065531_fn_rdma_FN5_20260505_065531_f7f28224/logs/run_20260505_065531.log
- Raw: /home/wangshouxin/native-rdma-web/functions/rdma/FN-5/history/web_20260505_065531_fn_rdma_FN5_20260505_065531_f7f28224/raw.json

## 关键证据

- 64 个 key 路由查询成功，primary 分布: {'192.168.0.218': 27, '192.168.0.214': 37}
- 本地 primary 写入未转发: key=fn_route_1777935331291_311062_0 primary=192.168.0.218
- 远端 primary 写入已转发到 peer: key=fn_route_1777935331292_311062_10 primary=192.168.0.214 transport=tcp_data_channel
- 本地 GET 与 peer GET 均完成同值读回；replica 为空样本数=43

## 统计口径

- 验证路由查询和分布计数；replica 为空时记录为当前路由策略细节。
- 验证 remote-primary key 的跨节点转发闭环，不只做路由表展示。
- 不验证跨交换机或多级转发性能；当前 remote-primary 转发通道为 TCP data channel。
