# 分布式共享数据管理系统 — 后端部署指南

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

1. **Ceph集群** 已部署并可用, `/etc/ceph/ceph.conf` 存在
2. **python3-rados** 已安装 (`apt install python3-rados` 或 `pip install rados`)
3. **两个节点** xfusion3 (192.168.0.3) 和 xfusion4 (192.168.0.4)

## 快速部署

### 1. 初始化Ceph Pool (任一节点执行一次)

```bash
cd ceph-backend
chmod +x setup_pools.sh
sudo ./setup_pools.sh
```

### 2. 启动后端服务

**节点A (xfusion3):**
```bash
cd ceph-backend
CURRENT_NODE=A PORT=5000 python3 app.py
```

**节点B (xfusion4):**
```bash
cd ceph-backend
CURRENT_NODE=B PORT=5001 python3 app.py
```

### 3. 配置前端

在前端HTML中设置API地址:
```html
<script>
  // 设置当前连接的后端地址
  window.API_BASE = 'http://192.168.0.3:5000';  // 或 xfusion4:5001
</script>
<script src="m3_sync.js"></script>
<script src="m5_perf.js"></script>
<script src="m6_tiering.js"></script>
```

## API 文档

### 通用

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/health` | GET | 健康检查, 返回Ceph连接状态 |

### M3: 跨节点同步

| 接口 | 方法 | 参数 | 说明 |
|------|------|------|------|
| `/api/m3/cluster` | GET | - | 检测集群和节点状态 |
| `/api/m3/objects` | GET | - | 列出sync_pool中所有对象 |
| `/api/m3/write` | POST | `{name, data, node}` | 写入对象 |
| `/api/m3/modify` | POST | `{name, data, node}` | 修改对象(版本+1) |
| `/api/m3/delete` | POST | `{name, node}` | 删除对象 |
| `/api/m3/read` | GET | `?name=xxx` | 读取单个对象 |

**关键点:** 两个节点的后端都连接同一个Ceph集群的`sync_pool`, 所以:
- 节点A写入 → 节点B立即可读(Ceph强一致性)
- 前端每2秒轮询刷新列表, 实时看到另一节点的操作

### M5: 性能测试

| 接口 | 方法 | 参数 | 说明 |
|------|------|------|------|
| `/api/m5/start` | POST | `{round: 1/2/3}` | 启动第N轮测试 |
| `/api/m5/status` | GET | - | 获取所有轮次结果 |
| `/api/m5/live` | GET | `?round=N` | 获取指定轮次实时数据 |
| `/api/m5/stream` | GET(SSE) | `?round=N` | SSE实时推送 |
| `/api/m5/reset` | POST | - | 重置所有测试数据 |

**测试流程:**
1. 预填充N个4KB对象到`perf_pool`
2. 启动16个并发线程, 70%读30%写, 持续15秒
3. 每秒采样IOPS/吞吐量/延迟/RDMA吞吐
4. 结束后汇总P50/P90/P99

### M6: 分级存储

| 接口 | 方法 | 参数 | 说明 |
|------|------|------|------|
| `/api/m6/start` | POST | - | 启动分级存储演示(6步自动流程) |
| `/api/m6/status` | GET | - | 获取当前步骤/层级分布/事件 |
| `/api/m6/objects` | GET | - | 获取所有对象详情(含层级和热度) |
| `/api/m6/stream` | GET(SSE) | - | SSE实时推送状态变化 |
| `/api/m6/reset` | POST | - | 重置演示 |

**演示6步:**
1. 写入100个军事对象到warm_pool (SSD温层)
2. 模拟访问: 10个高频, 20个中频, 70个不访问
3. 冷热识别: 高频→热层(ramfs), 无访问→冷层(cold_pool)
4. 冷数据快照: `rados mksnap` 创建Ceph快照
5. 回访回迁: 部分冷数据被访问, 自动提升回温层
6. 再次分层: 持续分层, 体现自动化能力

## 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `CEPH_CONF` | `/etc/ceph/ceph.conf` | Ceph配置文件路径 |
| `CURRENT_NODE` | `A` | 当前节点标识 |
| `PORT` | `5000` | Flask监听端口 |
| `SYNC_POOL` | `sync_pool` | M3同步池名 |
| `PERF_POOL` | `perf_pool` | M5性能池名 |
| `WARM_POOL` | `warm_pool` | M6温层池名 |
| `COLD_POOL` | `cold_pool` | M6冷层池名 |
| `HOT_PATH` | `/mnt/hot` | M6热层ramfs路径 |

## 故障排查

1. **连接Ceph失败**: 检查 `/etc/ceph/ceph.conf` 和 keyring
2. **Pool不存在**: 运行 `setup_pools.sh`
3. **rados模块找不到**: `apt install python3-rados` 或确保用系统Python
4. **RDMA延迟高**: 检查 `ibstat` 和网卡配置
5. **SSE断开**: 前端会自动降级为轮询模式
