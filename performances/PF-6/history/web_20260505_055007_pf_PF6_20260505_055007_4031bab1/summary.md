# PF-6 Summary

- Metric: 多级存储读写能力
- Source: `docs/性能要求.md` 第 6 条
- Generated At: 2026-05-05T05:51:02+0800
- Key Result: write=7.061 GB/s, read=20.696 GB/s
- Threshold: 写入 >= 10GB/s；读取 >= 20GB/s
- Result: FAIL
- Result Dir: /home/wangshouxin/native-rdma-web/performances/PF-6/history/web_20260505_055007_pf_PF6_20260505_055007_4031bab1
- Raw JSON: /home/wangshouxin/native-rdma-web/performances/PF-6/history/web_20260505_055007_pf_PF6_20260505_055007_4031bab1/raw.json
- Run Log: /home/wangshouxin/native-rdma-web/performances/PF-6/history/web_20260505_055007_pf_PF6_20260505_055007_4031bab1/logs/run.log

## 写入测试

| Key | Value |
|---|---:|
| `write_gbs` | 7.061 |
| `write_tx_bytes` | 70612036074 |
| `write_ops` | 6733.0 |
| `write_fail` | 36278 |
| `write_degraded` | 0 |

## 读取测试

| Key | Value |
|---|---:|
| `read_gbs` | 20.696 |
| `read_rx_bytes` | 206955286227 |
| `read_ops_total` | 197367 |
| `read_fail` | 0 |
| `read_avg_resp_bytes` | 1048581 |
| `read_hit_ratio` | 1.0 |

## 统计口径

- 写入带宽基于 req_bytes（客户端→服务端实际字节），读取带宽基于 resp_bytes（服务端→客户端实际字节）。
- 1MB 对象，shared keyspace=512。
- 测试前重启数据面设置 SLAB_SLOT_SIZE=1048576。
