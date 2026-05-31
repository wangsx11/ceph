# PF-6 Summary

- Metric: 多级存储读写能力
- Source: `docs/性能要求.md` 第 6 条
- Generated At: 2026-05-27T12:56:04+0800
- Key Result: write=10.816 GB/s, read=21.622 GB/s
- Threshold: 写入 >= 10GB/s；读取 >= 20GB/s
- Result: PASS
- Result Dir: /home/wangshouxin/native-rdma-web/performances/PF-6
- Raw JSON: /home/wangshouxin/native-rdma-web/performances/PF-6/raw.json
- Run Log: /home/wangshouxin/native-rdma-web/performances/PF-6/logs/run.log

## 写入测试

| Key | Value |
|---|---:|
| `write_gbs` | 10.816 |
| `write_tx_bytes` | 54077872349 |
| `write_ops` | 10311.0 |
| `write_fail` | 0 |
| `write_degraded` | 0 |

## 读取测试

| Key | Value |
|---|---:|
| `read_gbs` | 21.622 |
| `read_rx_bytes` | 216218450781 |
| `read_ops_total` | 206201 |
| `read_fail` | 0 |
| `read_avg_resp_bytes` | 1048581 |
| `read_hit_ratio` | 1.0 |

## 统计口径

- 写入带宽基于 req_bytes（客户端→服务端实际字节），读取带宽基于 resp_bytes（服务端→客户端实际字节）。
- 1MB 对象，shared keyspace=512。
- 测试前重启数据面设置 SLAB_SLOT_SIZE=1048576。
