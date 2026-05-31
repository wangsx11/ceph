# Native RDMA 演示 Dashboard 接口说明

## 架构概览

```
┌─────────────────┐     RDMA网络      ┌─────────────────┐
│  节点A xfusion3  │◄──────────────────►│  节点B xfusion4  │
│  前线指挥所       │                    │  后方指挥中心     │
│  Flask:5000      │                    │  Flask:5001      │
│  前端Dashboard   │                    │  前端Dashboard   │
└────────┬────────┘                    └────────┬────────┘
         │                                       │
         ▼              Ceph 集群                 ▼
    ┌─────────────────────────────────────────────────┐
    │  sync_pool (M3同步)  │  perf_pool (M5性能测试)   │
    │  warm_pool (M6温层SSD) │ cold_pool (M6冷层HDD)  │
    │              + /mnt/hot (M6热层ramfs)            │
    └─────────────────────────────────────────────────┘
```

## 前置条件

1. 两个节点 xfusion3 / xfusion4 已按 `native_rdma/deploy/*.env` 配置。
2. 在仓库根执行主入口：

```bash
cd native_rdma
bash start.sh
```

3. 浏览器打开本端 Flask：`http://<xfusion3-ip>:5000/`。

## API 文档

### 通用 / 状态

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/cluster/status` | GET | 数据面、peer、RDMA/TCP data channel 和指标状态 |
| `/api/metrics` | GET | 共享内存指标快照 |

### M3: 跨节点同步

| 接口 | 方法 | 参数 | 说明 |
|------|------|------|------|
| `/api/demo3/cluster` | GET | - | 检测 A/B 两端演示视图 |
| `/api/demo3/objects` | GET | - | 列出跨节点对象 |
| `/api/demo3/write` | POST | `{name, data}` | 写入对象 |
| `/api/demo3/modify` | POST | `{name, data}` | 修改对象 |
| `/api/demo3/delete` | POST | `{name}` | 删除对象 |
| `/api/demo3/read` | GET | `?name=xxx` | 读取单个对象 |

**关键点:** 页面通过本端 `/api/demo3/*` 和 `/api/peer/demo3/*` 访问两端 Flask，后端再走真实 RDMA 数据面，不依赖浏览器跨源直连 peer。

### M5: 性能测试

| 接口 | 方法 | 参数 | 说明 |
|------|------|------|------|
| `/api/demo5/start` | POST | `{round: 1/2/3}` | 启动第 N 轮对象规模负载 |
| `/api/demo5/status` | GET | - | 获取所有轮次结果 |
| `/api/demo5/live` | GET | `?round=N` | 获取指定轮次实时数据 |
| `/api/demo5/stream` | GET(SSE) | `?round=N` | SSE 实时推送 |
| `/api/demo5/reset` | POST | - | 重置演示数据 |

**测试流程:**
1. 按轮次增加对象规模。
2. 施加持续并发读写负载。
3. 采样 IOPS、吞吐、延迟分布和网络使用率。
4. 汇总每轮曲线与通过状态。

### M6: 分级存储

| 接口 | 方法 | 参数 | 说明 |
|------|------|------|------|
| `/api/demo6/start` | POST | - | 启动分级存储演示 |
| `/api/demo6/status` | GET | - | 获取当前步骤、层级分布、迁移事件和快照 |
| `/api/demo6/objects` | GET | - | 获取对象详情，含层级和热度 |
| `/api/demo6/stream` | GET(SSE) | - | SSE 实时推送状态变化 |
| `/api/demo6/reset` | POST | - | 重置演示 |

**演示6步:**
1. 写入对象并产生真实访问行为。
2. 根据热度将对象分布到 DRAM / NVMe / HDD。
3. 展示迁移事件、触发条件和前后层级。
4. 冷数据下沉后触发快照。
5. 后续访问使对象回迁到高层级。

## 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `NR_DASH_DIR` | 仓库根 `dashboard/` | 演示前端静态文件目录 |
| `NR_PEER_URL` | 空 | peer Flask 地址，用于 `/api/peer/*` 反向代理 |
| `NR_ROLE` | `A` | 当前节点标识 |
| `NR_CTRL_PORT` | `5000` | Flask 监听端口 |
| `NR_UDS_PATH` | `/tmp/native_rdma-dp.sock` | 数据面 UDS |
| `NR_METRICS_SHM` | `/tmp/native_rdma-metrics.shm` | 指标共享内存 |

## 故障排查

1. **数据面离线**: 检查 `cd native_rdma && bash start.sh` 输出和 `native_rdma/logs/dp_*.log`。
2. **peer 不在线**: 检查 `NR_PEER_URL`、xfusion4 数据面和 `/api/cluster/status`。
3. **远程浏览器请求打到 localhost**: 当前脚本默认使用 `location.origin`，如需跨主机代理可显式设置 `window.API_BASE`。
4. **SSE 断开**: 前端会自动降级为轮询模式。
