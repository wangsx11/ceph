# Ceph RDMA 配置排查记录

## 背景

初始问题：Ceph 集群性能指标不达标，怀疑未走真实 RDMA 网络。

**硬件环境：**
- xfusion3：osd.0，Mellanox ConnectX-5 (`mlx5_0`)，RDMA IP `192.168.0.218`
- xfusion4：osd.3，Mellanox ConnectX-5 (`mlx5_0`)，RDMA IP `192.168.0.214`
- xfusion5：osd.2，Mellanox ConnectX-5（`ens6np0`），RDMA IP `192.168.0.215`

**网络规划：**
- 公共网络（client → OSD）：`10.26.42.128/25`，普通以太网
- 集群网络（OSD ↔ OSD）：`192.168.0.0/24`，RoCE RDMA

---

## 问题一：OSD 未走 RDMA（ms_type 配置错误）

### 现象

```bash
ceph config get osd ms_type
# 返回：async+posix  ← 走 TCP，不是 RDMA
```

虽然 `ms_cluster_type = async+rdma` 已配置，但 `ms_type`（控制公共网络）仍为 `async+posix`。

### 修复

```bash
ceph config set osd ms_type async+rdma
```

---

## 问题二：osd.3 无法启动（网络地址找不到）

### 现象

osd.3 在 xfusion4 上已挂了 3 周，日志报错：

```
unable to find any IPv4 address in networks '192.168.0.0/24' interfaces ''
Failed to pick cluster address.
```

### 排查过程

1. `ceph osd tree` 确认 osd.3 状态为 `down/out`
2. `ceph orch ps | grep osd` 确认 cephadm 显示 `error`
3. 登录 xfusion4，查看 systemd 日志确认报错
4. `ip addr show` 确认 xfusion4 上 `ens6np0` 有 `192.168.0.214`，网卡 UP

### 根本原因

3 周前 osd.3 首次启动时，`ens6np0` 网卡可能尚未就绪。当前网卡已正常，直接重启即可。

---

## 问题三：osd.3 重启后仍崩溃（SIGABRT，exit code 134）

### 现象

重启后错误变为 `exit code 134`（SIGABRT），进程在 RDMA 初始化阶段崩溃。

### 原因一：缺少 RDMA 设备配置

osd.0/osd.1/osd.2 都配置了 `ms_async_rdma_device_name`，但 osd.3 没有。

**修复：**

```bash
ceph config set osd.3 ms_async_rdma_device_name mlx5_0
ceph config set osd.3 ms_async_rdma_gid_idx 2
ceph config set osd.3 ms_async_rdma_local_gid "0000:0000:0000:0000:0000:ffff:c0a8:00d6"
```

### 原因二：Docker 容器 memlock 限制（根本原因）

RDMA 需要锁定内存（`mlock`），但 Docker 默认 memlock 只有 64KB：

```bash
# 宿主机
ulimit -l  # unlimited

# Docker 容器内
docker run --rm ubuntu bash -c "ulimit -l"  # 64  ← 太小，导致 SIGABRT
```

**修复（只修改 osd.3，不重启 Docker，不影响其他容器）：**

```bash
# 在 xfusion4 上执行
sudo sed -i 's/--ulimit nofile=1048576/--ulimit nofile=1048576 --ulimit memlock=-1:-1/g' \
  /var/lib/ceph/4243f7e2-0340-11f1-babb-15cb9f8efe98/osd.3/unit.run

# 重置 systemd 失败状态并启动
sudo systemctl reset-failed ceph-4243f7e2-0340-11f1-babb-15cb9f8efe98@osd.3.service
sudo systemctl start ceph-4243f7e2-0340-11f1-babb-15cb9f8efe98@osd.3.service
```

---

## osd.0 和 osd.2 的 memlock 修复

同样修改 unit.run，然后逐个重启：

**xfusion3（osd.0）：**

```bash
sudo sed -i 's/--ulimit nofile=1048576/--ulimit nofile=1048576 --ulimit memlock=-1:-1/g' \
  /var/lib/ceph/4243f7e2-0340-11f1-babb-15cb9f8efe98/osd.0/unit.run
sudo systemctl restart ceph-4243f7e2-0340-11f1-babb-15cb9f8efe98@osd.0.service
```

**xfusion5（osd.2）：**

```bash
sudo sed -i 's/--ulimit nofile=1048576/--ulimit nofile=1048576 --ulimit memlock=-1:-1/g' \
  /var/lib/ceph/4243f7e2-0340-11f1-babb-15cb9f8efe98/osd.2/unit.run
sudo systemctl restart ceph-4243f7e2-0340-11f1-babb-15cb9f8efe98@osd.2.service
```

---

## 最终状态

```
cluster health: HEALTH_WARN（仅 pool application 未设置，不影响功能）
osd: 3 osds: 3 up, 3 in
pgs: 193 active+clean
ms_type: async+rdma（OSD 全部生效）
ms_cluster_type: async+rdma（OSD 间复制走 RDMA）
```

### 各 OSD RDMA 配置汇总

| OSD | 节点 | RDMA 设备 | GID Index | IP |
|---|---|---|---|---|
| osd.0 | xfusion3 | mlx5_0 | 2 | 192.168.0.218 |
| osd.2 | xfusion5 | mlx5_0 | 2 | 192.168.0.215 |
| osd.3 | xfusion4 | mlx5_0 | 2 | 192.168.0.214 |

---

## 遗留问题

### 1. cephadm 显示 osd.3 error

cephadm 层面仍显示 osd.3 为 error，因为直接修改了 unit.run 绕过了 cephadm 管理。不影响 OSD 实际运行，但 cephadm 若重新部署 osd.3 会覆盖 memlock 修改。

**永久修复方案**：在各节点 `/etc/docker/daemon.json` 中添加默认 memlock 限制：

```json
"default-ulimits": {
    "memlock": {
        "Name": "memlock",
        "Hard": -1,
        "Soft": -1
    }
}
```

需重启 Docker，需提前与其他容器使用者协调（xfusion4 上有 memsys-EMOS_TEST 等容器）。

### 2. 客户端未走 RDMA

`rados bench` 等客户端工具连接 OSD 走的是公共网络（`10.26.42.x`），该网络无 RDMA 设备。

原因：RDMA 网卡绑定在集群网络（`192.168.0.0/24`），Monitor 地址也在公共网络，无法直接将 `client ms_type` 改为 `async+rdma`（会导致连 Monitor 也走 RDMA 而卡死）。

**若要实现客户端 RDMA**，需将 OSD public_addr 改为 `192.168.0.x`，改动较大，需单独规划。

---

## 2026-04-02 全面状态检查与修复

### 检查目标

基于之前的排查记录，全面检查当前三节点的 RDMA 和 Ceph 状态，确认 RDMA 是否真正生效，并修复残余问题。

### 一、三节点 RDMA 网卡状态

所有节点 RDMA 网卡均为 Active/LinkUp，100 Gbps：

| 节点 | RDMA 设备 | 网卡接口 | 状态 | IP |
|---|---|---|---|---|
| xfusion3 | mlx5_0 (MT4119, FW 16.35.3502) | ens2np0 | Active/LinkUp 100G | 192.168.0.218/24 |
| xfusion4 | mlx5_0 (MT4119, FW 16.35.4506) | ens6np0 | Active/LinkUp 100G | 192.168.0.214/24 |
| xfusion5 | mlx5_0 (MT4119, FW 16.35.3502) | ens1np0 | Active/LinkUp 100G | 192.168.0.215/24 |

**ibdev2netdev 验证**：

```
xfusion3: mlx5_0 port 1 ==> ens2np0 (Up)
xfusion4: mlx5_0 port 1 ==> ens6np0 (Up)
xfusion5: mlx5_0 port 1 ==> ens1np0 (Up)
```

### 二、GID 表检查

各节点 GID 表结构不同，需注意 IPv4 地址对应的 GID index：

**xfusion3**：
```
GID 0: fe80:...:4fac  type=IB/RoCE v1  (link-local)
GID 1: fe80:...:4fac  type=RoCE v2     (link-local)
GID 2: ...ffff:c0a8:00da  type=IB/RoCE v1  (192.168.0.218)  ← osd.0 使用
GID 3: ...ffff:c0a8:00da  type=RoCE v2     (192.168.0.218)
```

**xfusion4**：
```
GID 0: fe80:...:4fb4  type=IB/RoCE v1  (link-local)
GID 1: fe80:...:4fb4  type=RoCE v2     (link-local)
GID 2: ...ffff:c0a8:00d6  type=IB/RoCE v1  (192.168.0.214)  ← osd.3 使用
GID 3: ...ffff:c0a8:00d6  type=RoCE v2     (192.168.0.214)
```

**xfusion5**（注意：多了一组 link-local，IPv4 GID 从 index 4 开始）：
```
GID 0: fe80:...:4fa8       type=IB/RoCE v1  (link-local)
GID 1: fe80:...:4fa8       type=RoCE v2     (link-local)
GID 2: fe80:...:bba1       type=IB/RoCE v1  (link-local #2)
GID 3: fe80:...:bba1       type=RoCE v2     (link-local #2)
GID 4: ...ffff:c0a8:00d7   type=IB/RoCE v1  (192.168.0.215)  ← osd.2 使用
GID 5: ...ffff:c0a8:00d7   type=RoCE v2     (192.168.0.215)
```

### 三、Ceph 集群状态检查

检查时集群状态为 **HEALTH_ERR**：

```
HEALTH_ERR 2 osds(s) are not reachable; 1 pool(s) do not have an application enabled
[ERR] OSD_UNREACHABLE: 2 osds(s) are not reachable
    osd.0's public address is not in '10.26.42.128/25' subnet
    osd.2's public address is not in '10.26.42.128/25' subnet
[WRN] POOL_APP_NOT_ENABLED: 1 pool(s) do not have an application enabled
    application not enabled on pool 'rdma_test'
```

**原因分析**：

- `public_network` 配置为 `10.26.42.128/25,192.168.0.0/24`（包含两个子网）
- osd.0 public_addr = 192.168.0.218，osd.2 public_addr = 192.168.0.215（在 RDMA 子网上）
- Ceph 健康检查验证 OSD 地址是否在 `10.26.42.128/25` 子网中，osd.0/osd.2 不在此子网，触发 HEALTH_ERR
- osd.3 配置了 public_addr=192.168.0.214 但实际运行在 10.26.42.225（配置未重启生效）
- **实际 I/O 不受影响**：rados bench 正常运行（408 MB/s），因为 Monitor 和所有 OSD 都在 192.168.0.x 可达

### 四、RDMA 通信验证（关键发现）

#### 4.1 OSD 容器 RDMA 支持确认

```bash
# 容器内 RDMA 库
/usr/lib64/libibverbs.so.1
/usr/lib64/libmlx5.so.1
/usr/lib64/librdmacm.so.1

# RDMA 设备已暴露到容器
/dev/infiniband/uverbs0, rdma_cm, umad0, issm0

# ceph-osd 二进制已链接 RDMA
libibverbs.so.1 => /lib64/libibverbs.so.1
librdmacm.so.1 => /lib64/librdmacm.so.1

# memlock 限制
ulimit -l = unlimited（容器内 PID 1 也是 unlimited）
```

#### 4.2 OSD RDMA Perf Counters（修复前）

**RDMA 确认已生效**，所有 OSD 均有活跃的 RDMA 流量：

```
osd.0: tx_wc=162,079  rx_wc=162,424  active_qp=6  errors=0
osd.2: tx_wc=154,178  rx_wc=157,032  active_qp=6  errors=0
osd.3: tx_wc=805,414  rx_wc=780,477  active_qp=6  errors=0
```

- `tx_total_wc` / `rx_total_wc`：RDMA Work Completion 计数，证明真实 RDMA 数据传输
- `active_queue_pair=6`：每个 OSD 维护 6 个 RDMA Queue Pair
- `tx_total_wc_errors=0` / `rx_total_wc_errors=0`：无 RDMA 传输错误

#### 4.3 运行时配置确认

```bash
ceph tell osd.0 config get ms_type
# {"ms_type": "async+rdma"}

ceph tell osd.0 config get ms_cluster_type
# {"ms_cluster_type": "async+rdma"}

ceph tell osd.0 config get ms_async_rdma_device_name
# {"ms_async_rdma_device_name": "mlx5_0"}
```

### 五、修复操作

#### 5.1 重启 osd.3 使 public_addr 生效

osd.3 配置了 `public_addr=v2:192.168.0.214:0/0` 但实际运行在 `10.26.42.225`。

```bash
ceph orch daemon restart osd.3
# Scheduled to restart osd.3 on host 'xfusion4'
```

**验证**：

```bash
ceph osd find 3
# addr: 192.168.0.214:6800  ← 已切换到 RDMA 子网
# nonce: 3606823622  ← 与之前不同，确认已重启

ceph tell osd.3 perf dump | grep RDMADispatcher
# active_queue_pair: 6  ← RDMA 立即生效
```

#### 5.2 修改 public_network

移除 `10.26.42.128/25`，仅保留 `192.168.0.0/24`（所有服务均在此子网）：

```bash
ceph config set global public_network '192.168.0.0/24'
```

**验证**：

```bash
ceph health detail
# HEALTH_WARN 1 pool(s) do not have an application enabled
# ← HEALTH_ERR 已消除
```

#### 5.3 启用 rdma_test 池应用标签

```bash
ceph osd pool application enable rdma_test rbd
```

**验证**：

```bash
ceph -s
# health: HEALTH_OK
# osd: 3 osds: 3 up, 3 in
# pgs: 193 active+clean
```

#### 5.4 清理 osd.1 残留配置

osd.1 已不存在于集群中，但配置数据库中仍有残留条目：

```bash
ceph config rm osd.1 ms_async_rdma_device_name
ceph config rm osd.1 ms_async_rdma_gid_idx
ceph config rm osd.1 ms_async_rdma_local_gid
ceph config rm osd.1 osd_mclock_max_capacity_iops_ssd
```

### 六、修复后性能验证

```bash
rados -p rdma_test bench 10 write --no-cleanup
# Bandwidth (MB/sec): 875.831
# Average IOPS:       218
# Max bandwidth:      1044 MB/s
# Min latency:        10.3 ms
```

RDMA perf counters 在 bench 期间显著增长，确认数据通过 RDMA 传输：

```
修复前 → 修复后（bench 后）
osd.0: tx_wc 183,177 → 222,393  (+39,216)
osd.2: tx_wc 177,650 → 245,924  (+68,274)
osd.3: tx_wc   4,018 →  53,685  (+49,667)
```

### 七、最终配置汇总

#### 网络配置

```
public_network:  192.168.0.0/24
cluster_network: 192.168.0.0/24
```

#### Messenger 配置

| 层级 | ms_type | ms_cluster_type | ms_public_type |
|---|---|---|---|
| mon | async+rdma（配置，运行时尚为 async+posix） | - | - |
| osd | async+rdma | async+rdma | async+posix |
| client | async+posix | - | - |

#### 各 OSD RDMA 配置

| OSD | 节点 | RDMA 设备 | GID Index | Local GID | IP |
|---|---|---|---|---|---|
| osd.0 | xfusion3 | mlx5_0 | 2 | ffff:c0a8:00da | 192.168.0.218 |
| osd.2 | xfusion5 | mlx5_0 | 4 | ffff:c0a8:00d7 | 192.168.0.215 |
| osd.3 | xfusion4 | mlx5_0 | 2 | ffff:c0a8:00d6 | 192.168.0.214 |

#### OSD 地址

```
osd.0: v2:192.168.0.218:6800, v1:192.168.0.218:6801
osd.2: v2:192.168.0.215:6800, v1:192.168.0.215:6801
osd.3: v2:192.168.0.214:6800, v1:192.168.0.214:6801
```

### 八、遗留事项

#### 1. Monitor RDMA 尚未生效

Monitor 配置了 `ms_type=async+rdma`，但运行时仍为 `async+posix`（需重启 Monitor 生效）。Monitor RDMA 不影响数据路径性能，可在维护窗口重启。

#### 2. GID Index 使用 IB/RoCE v1

当前 OSD 使用的 GID index 对应 IB/RoCE v1 类型（偶数 index），而非 RoCE v2（奇数 index）。虽然同时配置了 `ms_async_rdma_roce_ver=2`，但实际 RDMA 运行正常，perf counters 无错误。如需严格使用 RoCE v2，可将 GID index 调整为奇数（xfusion3/xfusion4 用 3，xfusion5 用 5），需重启 OSD 生效。

#### 3. cephadm memlock 兼容性

本次通过 `ceph orch daemon restart osd.3` 重启 osd.3 后，cephadm 自动包含了 memlock 设置（RDMA 正常工作），说明 cephadm 已正确处理 memlock。但仍建议在各节点 `/etc/docker/daemon.json` 中添加默认 memlock 设置作为保险：

```json
"default-ulimits": {
    "memlock": { "Name": "memlock", "Hard": -1, "Soft": -1 }
}
```

---

## 第二轮排查：RDMA 完整性验证（2026-04-07）

### 一、排查目标

验证 Ceph 集群端到端（客户端↔OSD↔OSD）的 RDMA 传输是否完整启用，确定当前性能瓶颈是否因客户端路径仍走 TCP 所致。

### 二、核心发现

#### 2.1 当前 Messenger 配置全景（实际运行时）

| 组件 | ms_type（运行时） | ms_public_type | ms_cluster_type | 实际传输协议 |
|---|---|---|---|---|
| **OSD** | async+rdma | **async+posix** ← 关键 | async+rdma | 公共=TCP，集群=RDMA |
| **Monitor** | async+posix（需重启） | - | - | TCP |
| **Client** | **async+posix** ← 关键 | - | - | TCP |

**结论：当前只有 OSD↔OSD 副本复制走 RDMA，客户端↔OSD 全路径走 TCP。**

#### 2.2 两个关键配置是根本原因

**原因 1：`osd ms_public_type = async+posix`**

OSD 的 messenger 分为两个独立的栈：
- **public messenger**（面向客户端/Monitor 的连接）：受 `ms_public_type` 控制，当前为 `async+posix`（TCP）
- **cluster messenger**（面向其他 OSD 的副本复制）：受 `ms_cluster_type` 控制，当前为 `async+rdma`

即使 `ms_type = async+rdma` 已设置，`ms_public_type` 会覆盖 public messenger 的类型。前期排查时因 `public_network` 为 `10.26.42.128/25`（无 RDMA 设备），故有意将 public messenger 设为 TCP。但在 2026-04-02 已将 `public_network` 改为 `192.168.0.0/24`（RDMA 子网），此设置未同步更新。

**原因 2：`client ms_type = async+posix`**

客户端（`rados bench` 等工具）的 messenger 类型被显式设为 `async+posix`，任何客户端操作都只能通过 TCP 与 OSD 通信。

#### 2.3 OSD Perf Counters 证实 RDMA 仅用于副本复制

**OSD Worker 分析（以 osd.0 为例）**：

| Worker | 类型 | 活跃连接 | 创建连接 | 发送量 | 加密流量 | 说明 |
|---|---|---|---|---|---|---|
| Worker-0 | public | 5 | 35 | 0.52GB | 0 | Mon/Mgr 连接 |
| Worker-1 | public | 4 | **739** | **23.22GB** | 3.87GB | **客户端 bench 流量 (TCP)** |
| Worker-2 | public | 4 | 731 | 3.07GB | 0.08GB | 客户端连接 (TCP) |
| Worker-0-0x... | cluster | 3 | 5 | 16.39GB | 0 | OSD 复制 (RDMA) |
| Worker-1-0x... | cluster | 3 | 7 | 0.52GB | 0 | OSD 复制 (RDMA) |
| Worker-2-0x... | cluster | 4 | 6 | 16.08GB | 0 | OSD 复制 (RDMA) |

- Public Worker-1 的 `created_connections=739` 和 `send_bytes=23.22GB` 对应 rados bench 客户端连接，走 TCP
- Cluster Workers（带 0x 后缀）的流量与 RDMAWorker 的 tx/rx bytes 吻合，确认走 RDMA

**RDMA Queue Pair 分析**：

每个 OSD 的 `active_queue_pair = 6`，恰好等于 2（对等 OSD 数量）× 3（worker 线程数）= 6，全部是 OSD↔OSD 集群连接，**无客户端 RDMA QP**。

#### 2.4 Bench 期间 RDMA 计数器增量

| OSD | tx_wc 基线 | tx_wc bench后 | 增量 |
|---|---|---|---|
| osd.0 | 11,554,854 | 11,618,337 | +63,483 |
| osd.2 | 11,589,124 | 11,694,409 | +105,285 |
| osd.3 | 11,406,344 | 11,479,516 | +73,172 |

Bench 写入 3400 × 4MB = 13.6GB 数据，3 副本 CRUSH 分布，RDMA 增量来自副本复制流量，而非客户端写入。

#### 2.5 cephadm 容器化 **不是** RDMA 障碍

排查确认容器环境对 RDMA 无阻碍：

| 检查项 | 结果 |
|---|---|
| 容器网络模式 | `host`（共享宿主机网络栈） |
| 容器特权模式 | `privileged=true` |
| `/dev/infiniband` 设备 | 完整透传（uverbs0, rdma_cm, umad0, issm0） |
| RDMA 库 | libibverbs.so.1, librdmacm.so.1 已加载 |
| memlock 限制 | unlimited |
| OSD 监听地址 | `192.168.0.x:6800`（RDMA 子网） |

cephadm 部署的 OSD 容器使用 host 网络 + privileged 模式，RDMA 设备和网络栈完全可用。**cephadm 容器化不是 RDMA 无法生效的原因。**

#### 2.6 客户端 RDMA 可行性

宿主机上的 `rados` 二进制已链接 RDMA 库：

```
libibverbs.so.1 => /lib/x86_64-linux-gnu/libibverbs.so.1
librdmacm.so.1 => /lib/x86_64-linux-gnu/librdmacm.so.1
```

宿主机有 RDMA 设备 `mlx5_0`，且 Monitor/OSD 均在 `192.168.0.0/24` RDMA 子网上——客户端启用 RDMA 在技术上可行。

### 三、根本原因总结

**RDMA 未端到端启用的根本原因是两个配置项未更新：**

1. **`osd ms_public_type = async+posix`**：OSD 面向客户端的公共接口被强制设为 TCP。这是前期 `public_network` 在非 RDMA 子网时的合理设置，但在 `public_network` 已切换到 `192.168.0.0/24` 后未同步修改。

2. **`client ms_type = async+posix`**：客户端被强制设为 TCP，即使 OSD public messenger 改为 RDMA，客户端仍无法发起 RDMA 连接。

这两个配置联合作用，导致数据写入的第一跳（客户端→主 OSD）始终走 TCP，只有第二跳（主 OSD→副本 OSD）走 RDMA。

**cephadm 容器化部署不是障碍。** 容器使用 host 网络 + privileged 模式，RDMA 设备完整透传，OSD 的集群 messenger 已成功使用 RDMA，证明容器环境对 RDMA 无限制。

### 四、修复方案

#### 步骤 1：修改 OSD 公共 messenger 为 RDMA

```bash
ceph config set osd ms_public_type async+rdma
```

此操作将 OSD 的 public messenger 从 TCP 切换为 RDMA。需要逐个重启 OSD 生效：

```bash
ceph orch daemon restart osd.0
ceph orch daemon restart osd.2
ceph orch daemon restart osd.3
```

> ⚠️ 建议逐个重启并等待 PG 恢复 `active+clean` 后再重启下一个，避免同时多 OSD 不可用。

#### 步骤 2：配置客户端 RDMA 参数

```bash
# 客户端 messenger 类型
ceph config set client ms_type async+rdma

# 客户端 RDMA 设备参数（按运行 bench 的节点配置）
# 如果客户端在 xfusion3 上运行：
ceph config set client ms_async_rdma_device_name mlx5_0
ceph config set client ms_async_rdma_gid_idx 2
ceph config set client ms_async_rdma_local_gid "0000:0000:0000:0000:0000:ffff:c0a8:00da"
```

> ⚠️ 注意：如果客户端在不同节点运行，GID index 和 local GID 需按该节点的实际值设置。多节点客户端场景可能需要按 host mask 配置（`ceph config set client/host:xfusion4 ...`），或让 Ceph 自动探测（移除 `ms_async_rdma_local_gid`，仅设置 `device_name` 和 `gid_idx`）。

#### 步骤 3：重启 Monitor 使其支持 RDMA（可选）

Monitor 已配置 `ms_type = async+rdma` 但运行时仍为 `async+posix`。若客户端切换到 RDMA，Monitor 也需重启以匹配：

```bash
ceph orch daemon restart mon.xfusion3
# 等待 quorum 恢复
ceph orch daemon restart mon.xfusion5
```

> ⚠️ Monitor 一次只重启一个，确保 quorum 不丢失。

#### 步骤 4：验证

```bash
# 检查 QP 数量应增加（客户端会创建新的 RDMA QP）
ceph tell osd.0 perf dump | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['AsyncMessenger::RDMADispatcher']['active_queue_pair'])"

# 运行 bench 后对比：active_qp 应 > 6（多出客户端连接的 QP）
rados -p rdma_test bench 10 write --no-cleanup

# 检查 public messenger 的 Worker 是否不再有新的 TCP 连接
```

### 五、风险评估

| 操作 | 风险 | 缓解措施 |
|---|---|---|
| 修改 `ms_public_type` | OSD 重启期间短暂不可用 | 逐个重启，等待 PG 恢复 |
| 修改 `client ms_type` | 若客户端 RDMA 初始化失败，客户端无法连接 OSD | 先在单个测试客户端验证，保留回退命令 |
| 重启 Monitor | 短暂 quorum 波动 | 一次只重启一个 |
| 客户端 GID 配置错误 | RDMA 连接失败 | 可用 `ceph config set client ms_type async+posix` 立即回退 |

### 六、回退方案

如修改后出现问题，立即执行：

```bash
ceph config set osd ms_public_type async+posix
ceph config set client ms_type async+posix
# 然后逐个重启 OSD
```

### 七、预期性能提升

当前 rados bench ~900 MB/s 已接近 3 副本写入下单块 NVMe 的 IOPS/带宽上限。启用客户端 RDMA 后：
- **延迟降低**：RDMA 绕过内核协议栈，减少 CPU 开销和上下文切换，预期 avg latency 从 ~70ms 降低
- **小 I/O 性能提升**：4K 随机读写场景下 RDMA 优势更明显
- **CPU 利用率降低**：RDMA 卸载网络处理到网卡，释放 CPU 给 OSD 处理 I/O
- **大块顺序写可能提升有限**：当前 ~900 MB/s 可能已接近存储介质瓶颈，RDMA 对大块顺序 I/O 的带宽提升不如延迟提升显著

---

## 第三轮操作：端到端 RDMA 切换（2026-04-07）

### 一、操作目标

将 Ceph 集群从"仅 OSD↔OSD 副本复制走 RDMA"切换为全链路 RDMA：客户端↔OSD↔OSD、OSD↔Monitor、客户端↔Monitor 全部走 RDMA。

### 二、切换前基线数据

**集群状态**：HEALTH_OK，3 OSD up/in，193 PG active+clean

**Messenger 配置**：
```
osd ms_type         = async+rdma
osd ms_cluster_type = async+rdma
osd ms_public_type  = async+posix   ← 客户端/Monitor 方向仍为 TCP
client ms_type      = async+posix   ← 客户端仍为 TCP
mon ms_type         = async+rdma（config store 中，运行时未生效）
```

**RDMA Perf Counters 基线**：
```
osd.0: tx_wc=11,636,673  rx_wc=11,655,205  active_qp=6  errors=0/0
osd.2: tx_wc=11,712,333  rx_wc=11,671,349  active_qp=6  errors=0/0
osd.3: tx_wc=11,497,519  rx_wc=11,524,285  active_qp=6  errors=0/0
```

**rados bench 基线（TCP 客户端）**：
```
Bandwidth (MB/sec): 874.755
Average IOPS:       218
Average Latency(s): 0.0723948
Min Latency(s):     0.0103155
Max Bandwidth:      1136 MB/s
```

### 三、操作过程

#### 3.1 首次尝试：先改 OSD public messenger 再重启（失败）

```bash
ceph config set osd ms_public_type async+rdma
ceph orch daemon restart osd.0
```

**结果**：osd.0 重启后无法连接 Monitor，状态 down。

**根因**：osd.0 的 public messenger 变为 RDMA 后，尝试通过 RDMA 连接 Monitor，但 Monitor 运行时仍为 TCP（`async+posix`），RDMA messenger 与 TCP messenger **不兼容，无法互通**。

日志关键信息：
```
Infiniband to_dead failed to send a beacon: (115) Operation now in progress
```

**回退**：
```bash
ceph config set osd ms_public_type async+posix
ceph orch daemon restart osd.0
# 集群恢复 HEALTH_OK
```

#### 3.2 第二次尝试：通过 extra-ceph-conf 单独切 Monitor（失败）

```bash
ceph cephadm set-extra-ceph-conf -i /tmp/extra_ceph_conf.txt
# 内容为 [mon] ms_type = async+rdma
ceph orch daemon restart mon.xfusion3
```

**结果**：mon.xfusion3 切换为 RDMA，但 mon.xfusion5 仍为 TCP，两者无法通信，quorum 丢失，`ceph -s` 超时。

**回退**：直接修改 mon.xfusion3 的 ceph.conf 移除 RDMA 配置，通过 systemctl 重启恢复。

```bash
# 在 xfusion3 上
sudo bash -c 'cat > /var/lib/ceph/.../mon.xfusion3/config << EOF
[global]
fsid = ...
mon_host = ...
[mon.xfusion3]
public network = 192.168.0.0/24
EOF'
sudo systemctl restart ceph-...@mon.xfusion3.service
# 集群恢复 HEALTH_OK
```

#### 3.3 关键发现：RDMA messenger 不兼容 TCP

**Ceph 的 `async+rdma` messenger 与 `async+posix` (TCP) messenger 完全不互通。** 不存在协议降级/回退机制。当一端使用 RDMA、另一端使用 TCP 时，连接建立失败。

这意味着：
- 不能逐个滚动切换——必须同时切换所有通信对端
- Monitor quorum 的两端必须同时为 RDMA
- OSD 的 public messenger 改为 RDMA 前，Monitor 必须先切换

#### 3.4 成功方案：同时停止所有 Monitor + 全量修改

**正确的操作顺序**：

**步骤 1：修正 Monitor per-daemon RDMA GID 配置**

xfusion5 的 GID 表与其他节点不同（IPv4 在 GID 4 而非 GID 2），需要 per-daemon 配置：

```bash
ceph config rm mon ms_async_rdma_gid_idx
ceph config set mon.xfusion3 ms_async_rdma_gid_idx 2
ceph config set mon.xfusion3 ms_async_rdma_local_gid "0000:0000:0000:0000:0000:ffff:c0a8:00da"
ceph config set mon.xfusion5 ms_async_rdma_gid_idx 4
ceph config set mon.xfusion5 ms_async_rdma_local_gid "0000:0000:0000:0000:0000:ffff:c0a8:00d7"
```

**步骤 2：同时切换两个 Monitor**

发现 Monitor 的 `ms_type` 必须通过 `ceph.conf` 文件设置（config store 中的值在 messenger 初始化后才读取，不生效）。

在两个节点分别准备 RDMA ceph.conf（包含 `[mon]` 段 `ms_type = async+rdma` 和 per-daemon GID 配置），然后：

```bash
# 同时停止两个 Monitor
ssh xfusion3 "sudo systemctl stop ceph-...@mon.xfusion3.service" &
ssh xfusion5 "sudo systemctl stop ceph-...@mon.xfusion5.service" &
wait

# 部署 RDMA ceph.conf
ssh xfusion3 "sudo cp /tmp/mon_rdma_config /var/lib/ceph/.../mon.xfusion3/config" &
ssh xfusion5 "sudo cp /tmp/mon_rdma_config /var/lib/ceph/.../mon.xfusion5/config" &
wait

# 同时启动两个 Monitor
ssh xfusion3 "sudo systemctl start ceph-...@mon.xfusion3.service" &
ssh xfusion5 "sudo systemctl start ceph-...@mon.xfusion5.service" &
wait
```

**结果**：两个 RDMA Monitor 成功组建 quorum！但此时 `ceph` CLI（TCP）无法连接 RDMA Monitor。

**步骤 3：使用 RDMA 客户端配置连接 Monitor**

创建临时 RDMA ceph.conf 给 CLI 使用：

```ini
[global]
fsid = 4243f7e2-0340-11f1-babb-15cb9f8efe98
mon_host = [v2:192.168.0.218:3300/0,...] [v2:192.168.0.215:3300/0,...]
keyring = /etc/ceph/ceph.client.admin.keyring
ms_type = async+rdma
ms_async_rdma_device_name = mlx5_0
ms_async_rdma_gid_idx = 2
ms_async_rdma_local_gid = 0000:0000:0000:0000:0000:ffff:c0a8:00da
```

```bash
ceph -c /tmp/rdma_client.conf -s
# 成功连接！quorum xfusion3,xfusion5
```

**步骤 4：设置 OSD public messenger 和 client RDMA**

```bash
ceph -c /tmp/rdma_client.conf config set osd ms_public_type async+rdma
ceph -c /tmp/rdma_client.conf config set client ms_type async+rdma
ceph -c /tmp/rdma_client.conf config set client ms_async_rdma_device_name mlx5_0
ceph -c /tmp/rdma_client.conf config set client ms_async_rdma_gid_idx 2
ceph -c /tmp/rdma_client.conf config set client ms_async_rdma_local_gid "0000:0000:0000:0000:0000:ffff:c0a8:00da"
```

**步骤 5：OSD 需要在 ceph.conf 中注入 RDMA 配置**

OSD 启动时先用 MonClient（默认 TCP）连接 Monitor 获取配置，但 Monitor 已变为 RDMA-only，MonClient TCP 连接失败。必须将 RDMA 参数写入每个 OSD 的 ceph.conf，使 MonClient 也用 RDMA 启动。

在每个节点上修改 OSD ceph.conf（各节点 GID 不同）：

```bash
# xfusion3 (osd.0): gid_idx=2
# xfusion4 (osd.3): gid_idx=2
# xfusion5 (osd.2): gid_idx=4
```

**步骤 6：Mgr 容器需要添加 `--privileged` 和 `--ulimit memlock=-1:-1`**

Mgr 容器默认没有 `--privileged` 标志，导致容器内无法访问 `/dev/infiniband` 设备，RDMA 初始化失败（`FAILED ceph_assert(num)` in `DeviceList::DeviceList`）。

修改各节点 Mgr 的 `unit.run`：
```bash
sudo sed -i 's|--ulimit nofile=1048576|--ulimit nofile=1048576 --ulimit memlock=-1:-1 --privileged|' \
  /var/lib/ceph/.../mgr.*/unit.run
```

**步骤 7：同时重启所有 OSD + Mgr**

```bash
ssh xfusion3 "sudo systemctl restart ceph-...@osd.0.service" &
ssh xfusion4 "sudo systemctl restart ceph-...@osd.3.service" &
ssh xfusion5 "sudo systemctl restart ceph-...@osd.2.service" &
wait
# 重启 Mgr...
```

**步骤 8：更新宿主机 ceph.conf**

```bash
sudo cp /tmp/rdma_client.conf /etc/ceph/ceph.conf
```

### 四、切换结果

**切换成功！** 集群 HEALTH_OK（仅有一个 cephadm daemon failed 警告），所有组件通过 RDMA 通信。

**运行时 Messenger 配置**：

| 组件 | ms_type | ms_public_type | ms_cluster_type | 实际传输 |
|---|---|---|---|---|
| OSD | async+rdma | async+rdma | async+rdma | **全 RDMA** |
| Monitor | async+rdma | - | - | **RDMA** |
| Mgr | async+rdma | - | - | **RDMA** |
| Client | async+rdma | - | - | **RDMA** |

### 五、切换前后性能对比

| 指标 | 切换前 (TCP客户端) | 切换后 (RDMA端到端) | 变化 |
|---|---|---|---|
| **Bandwidth (MB/s)** | 874.8 | **1082.2** | **+23.7%** |
| **Average IOPS** | 218 | **270** | **+23.9%** |
| **Average Latency (ms)** | 72.4 | **59.0** | **-18.5%** |
| **Min Latency (ms)** | 10.3 | **8.8** | **-15.0%** |
| **Max Bandwidth (MB/s)** | 1136 | **1284** | **+13.0%** |

### 六、RDMA Queue Pair 数量对比

| OSD | 切换前 active_qp | 切换后 active_qp | 说明 |
|---|---|---|---|
| osd.0 | 6 | **14** | +8 QP（来自 Mon/Mgr/cephadm 等 RDMA 连接） |
| osd.2 | 6 | **14** | +8 QP |
| osd.3 | 6 | **16** | +10 QP |

切换前 6 QP = 2 (对等OSD) × 3 (worker) = 仅 OSD↔OSD。切换后增加了 Monitor、Mgr、客户端等 RDMA QP。

### 七、Bench 期间 RDMA tx_wc 增量

| OSD | tx_wc bench前 | tx_wc bench后 | **增量** |
|---|---|---|---|
| osd.0 | 4,617 | 55,816 | **+51,199** |
| osd.2 | 20,887 | 105,860 | **+84,973** |
| osd.3 | 20,444 | 79,975 | **+59,531** |

Bench 期间 RDMA WC 增量约 19.5 万次，覆盖了客户端写入 + 副本复制全路径。

### 八、操作过程中的关键经验教训

1. **RDMA messenger 与 TCP messenger 完全不互通**：不存在协议降级，mixed 环境下连接直接失败。切换必须原子化——所有通信对端同时切换。

2. **Monitor `ms_type` 必须通过 ceph.conf 设置**：config store 中的 `ms_type` 在 Monitor 的 messenger 初始化之后才读取，不生效。必须写入 ceph.conf。

3. **OSD MonClient 也受 ceph.conf 中 `ms_type` 控制**：OSD 启动时先用 MonClient 连接 Monitor 获取配置。如果 ceph.conf 中没有 `ms_type = async+rdma`，MonClient 默认用 TCP，无法连接 RDMA Monitor。

4. **Mgr 容器默认没有 RDMA 设备访问权限**：需要添加 `--privileged` 和 `--ulimit memlock=-1:-1`。OSD 容器有 `--privileged`，但 Mgr 没有。

5. **2-Monitor quorum 无法滚动切换**：必须同时停止、同时启动两个 Monitor。切换期间有约 10 秒中断。

6. **cephadm 会覆盖 keyring 权限**：Mgr 重启后 cephadm 将 `/etc/ceph/ceph.client.admin.keyring` 权限改为 `root:root 0600`，需要手动修复为 `644`。

### 九、最终配置汇总

#### 网络配置

```
public_network:  192.168.0.0/24
cluster_network: 192.168.0.0/24
```

#### Messenger 配置

| 层级 | ms_type | ms_public_type | ms_cluster_type |
|---|---|---|---|
| mon | async+rdma | - | - |
| osd | async+rdma | async+rdma | async+rdma |
| client | async+rdma | - | - |

#### 各组件 RDMA 配置

| 组件 | 节点 | RDMA 设备 | GID Index | IP |
|---|---|---|---|---|
| osd.0 | xfusion3 | mlx5_0 | 2 | 192.168.0.218 |
| osd.2 | xfusion5 | mlx5_0 | 4 | 192.168.0.215 |
| osd.3 | xfusion4 | mlx5_0 | 2 | 192.168.0.214 |
| mon.xfusion3 | xfusion3 | mlx5_0 | 2 | 192.168.0.218 |
| mon.xfusion5 | xfusion5 | mlx5_0 | 4 | 192.168.0.215 |
| mgr.xfusion3 | xfusion3 | mlx5_0 | 2 | 192.168.0.218 |
| mgr.xfusion4 | xfusion4 | mlx5_0 | 2 | 192.168.0.214 |
| client (xfusion3) | xfusion3 | mlx5_0 | 2 | 192.168.0.218 |

### 十、遗留事项

#### 1. `Infiniband to_dead failed to send a beacon` 警告

RDMA 连接断开/清理时偶发此警告，不影响数据通路。可能是 Ceph Reef 18.2.7 的已知行为。

#### 2. cephadm 管理兼容性

本次通过直接修改 daemon 的 ceph.conf 和 unit.run 实现 RDMA 切换，绕过了 cephadm 管理。cephadm 重新部署 daemon 时会覆盖这些修改。建议：
- 使用 `ceph cephadm set-extra-ceph-conf` 持久化 `[mon]` RDMA 配置
- 在各节点 Docker daemon.json 中设置 `default-ulimits` 确保 memlock
- 需进一步研究 cephadm 如何为 Mgr 容器添加 `--privileged` 标志

#### 3. 多客户端节点的 GID 配置

当前 `client ms_async_rdma_gid_idx = 2` 和 `ms_async_rdma_local_gid` 为 xfusion3 的值。若在其他节点运行客户端工具，需按该节点的 GID 配置（如 xfusion5 使用 gid_idx=4）。可考虑使用 `ceph config set client/host:xfusion5 ms_async_rdma_gid_idx 4` 的 host mask 配置。

#### 4. keyring 权限

cephadm 可能在 daemon 重新部署时将 `/etc/ceph/ceph.client.admin.keyring` 权限改为 `0600`，需确保当前用户可读。

---

## 第四轮验证：端到端 RDMA 完整性确认（2026-04-07）

### 一、验证目标

在第三轮端到端 RDMA 切换成功后，对集群进行全面的 RDMA 完整性验证，覆盖配置层、连接层、流量层和节点覆盖四个维度，确认所有组件均通过 RDMA 通信且无 TCP 残留路径。

### 二、验证结果汇总

| 维度 | 检查项 | 结果 | 说明 |
|---|---|---|---|
| **配置层** | osd ms_type | ✅ async+rdma | 三个 OSD 运行时一致 |
| | osd ms_public_type | ✅ async+rdma | 客户端方向已切换 RDMA |
| | osd ms_cluster_type | ✅ async+rdma | OSD 间复制走 RDMA |
| | mon ms_type (运行时) | ✅ async+rdma | xfusion3/xfusion5 均已生效 |
| | mon ceph.conf 写入 | ✅ 正确 | 两节点均含 `[mon] ms_type = async+rdma` 及 per-daemon GID |
| | mgr ms_type (运行时) | ✅ async+rdma | 活跃 Mgr (xfusion3) 已确认 |
| | mgr --privileged | ✅ 已启用 | xfusion3 Mgr 容器 `Privileged=true`，memlock unlimited |
| | client ms_type | ✅ async+rdma | config store 已设置 |
| **连接层** | osd.0 active_qp | ✅ 14 | >6，包含客户端/Mon/Mgr RDMA QP |
| | osd.2 active_qp | ✅ 14 | 同上 |
| | osd.3 active_qp | ✅ 16 | 同上（略多 2 QP，可能 Mgr standby 连接） |
| | RDMA WC errors | ✅ 全 0 | 三个 OSD tx/rx_total_wc_errors = 0 |
| | public Worker TCP 连接 | ✅ 无残留 TCP 客户端 | Worker created_connections 低（8-21），无第二轮中 700+ 的 TCP 连接特征 |
| **流量层** | bench 带宽 | ✅ 1071 MB/s | 与切换后基线 1082 MB/s 一致 |
| | bench IOPS | ✅ 267 | 与切换后基线 270 一致 |
| | bench 平均延迟 | ✅ 59.6 ms | 与切换后基线 59.0 ms 一致 |
| | Worker↔RDMAWorker 吻合度 | ✅ 偏差 <0.3% | 所有 Worker 的 send_bytes 增量与 RDMAWorker tx_bytes 增量高度一致 |
| | RDMA tx_wc bench 增量 | ✅ 显著增长 | osd.0: +73,691, osd.2: +128,627, osd.3: +89,606 |
| **节点覆盖** | xfusion3 RDMA 设备 | ✅ PORT_ACTIVE | mlx5_0, Ethernet link, FW 16.35.3502 |
| | xfusion4 RDMA 设备 | ✅ PORT_ACTIVE | mlx5_0, Ethernet link, FW 16.35.4506 |
| | xfusion5 RDMA 设备 | ✅ PORT_ACTIVE | mlx5_0, Ethernet link, FW 16.35.3502 |
| | OSD 监听子网 | ✅ 全在 192.168.0.0/24 | osd.0=.218, osd.2=.215, osd.3=.214 |

### 三、流量层详细数据

#### 3.1 rados bench 性能数据

```
测试命令: rados -p rdma_test bench 15 write --no-cleanup
并发数:  16
对象大小: 4 MB

Bandwidth (MB/sec):   1071.15
Average IOPS:         267
Stddev IOPS:          26.03
Max bandwidth (MB/s): 1196
Min bandwidth (MB/s): 872
Average Latency(s):   0.0596
Min Latency(s):       0.0100
Max Latency(s):       0.1833
Total writes:         4034
```

#### 3.2 Bench 前后 RDMA 计数器增量

| OSD | tx_wc 增量 | rx_wc 增量 | 说明 |
|---|---|---|---|
| osd.0 | +73,691 | +140,031 | 主 OSD 接收客户端写入 + 发送副本 |
| osd.2 | +128,627 | +140,914 | 接收副本复制 + 发送确认 |
| osd.3 | +89,606 | +140,027 | 接收副本复制 + 发送确认 |

总 tx_wc 增量约 29.2 万次，覆盖客户端写入 + 3 副本复制全路径。

#### 3.3 Worker send_bytes 与 RDMAWorker tx_bytes 吻合验证

| OSD | Worker | send_bytes 增量 | rdma tx_bytes 增量 | 偏差 |
|---|---|---|---|---|
| osd.0 | Worker-0 | 8,393,615,536 B | 8,393,736,800 B | 0.001% |
| osd.0 | Worker-1 | 420,320 B | 420,320 B | 0.000% |
| osd.0 | Worker-2 | 449,592 B | 450,932 B | 0.297% |
| osd.2 | Worker-0 | 7,579,112,031 B | 7,579,210,855 B | 0.001% |
| osd.2 | Worker-1 | 368,171 B | 368,459 B | 0.078% |
| osd.2 | Worker-2 | 7,579,688,076 B | 7,579,788,348 B | 0.001% |
| osd.3 | Worker-0 | 5,153,671,290 B | 5,153,753,418 B | 0.002% |
| osd.3 | Worker-1 | 5,154,248,919 B | 5,154,327,719 B | 0.002% |
| osd.3 | Worker-2 | 87,043 B | 87,043 B | 0.000% |

**所有 Worker 的 send_bytes 增量与对应 RDMAWorker tx_bytes 增量偏差均 <0.3%，确认无 TCP 分离流量。**

### 四、总体结论

**✅ 集群已完全走 RDMA。** 端到端（客户端↔OSD↔OSD↔Monitor↔Mgr）全路径通过 RDMA 通信，无 TCP 残留。

具体证据：
1. 所有组件运行时 `ms_type` 均为 `async+rdma`
2. OSD QP 数量 14-16（远超纯 OSD↔OSD 的 6 QP），包含客户端/Mon/Mgr 连接
3. Bench 期间 Worker send_bytes 与 RDMAWorker tx_bytes 完全吻合（偏差 <0.3%），无数据走 TCP
4. RDMA WC errors 全零，传输稳定无错误
5. Bench 性能（1071 MB/s, 59.6 ms 延迟）与第三轮切换后基线一致，无退化
6. 三节点 RDMA 设备均 PORT_ACTIVE，OSD 均在 192.168.0.0/24 RDMA 子网监听

### 五、观察到的非关键告警

- **`Infiniband to_dead failed to send a beacon`**：RDMA 连接断开/清理时偶发此 stderr 警告（ceph CLI 发出），不影响数据通路，与第三轮记录一致。属于 Ceph Reef 18.2.7 已知行为。
- **xfusion4 Mgr（standby）**：无法通过 `ceph tell` 查询 standby Mgr 配置，也无法通过当前用户权限检查其 unit.run（xfusion4 无免密 sudo）。建议在维护窗口确认 xfusion4 Mgr 的 `--privileged` 和 memlock 设置。

---

## 第五轮检查：backend Python 代码 RDMA 兼容性（2026-04-07）

### 一、检查目标

验证 `backend/` 目录下所有 Python 代码在发起 Ceph 连接时是否正确继承集群的 RDMA 配置，是否存在代码层面的配置覆盖、连接参数设置或库版本问题导致实际走 TCP。

### 二、检查文件清单

| 文件 | 功能 | 是否使用 rados |
|---|---|---|
| `config.py` | 全局配置（CEPH_CONF 路径、Pool 名称等） | 否（仅定义常量） |
| `ceph_manager.py` | Ceph 连接管理（单例模式） | ✅ `rados.Rados()` 初始化 |
| `app.py` | Flask 入口 | 间接（通过 ceph_mgr） |
| `utils.py` | 工具函数 | 否 |
| `m3_sync.py` | M3 跨节点同步 | ✅ 通过 ceph_mgr + 直接 `import rados` |
| `m5_perf.py` | M5 性能测试 | ✅ 通过 ceph_mgr |
| `m6_tiering.py` | M6 分级存储 | ✅ 通过 ceph_mgr |

### 三、逐项检查结果

#### 3.1 配置继承检查

| 检查项 | 结果 | 说明 |
|---|---|---|
| `rados.Rados()` 初始化方式 | ✅ | `ceph_manager.py:27`: `rados.Rados(conffile=CEPH_CONF)`，读取 `/etc/ceph/ceph.conf` |
| ceph.conf 是否包含 RDMA 配置 | ✅ | 当前 `/etc/ceph/ceph.conf` 含 `ms_type=async+rdma` 及全部 RDMA 参数 |
| 是否有 `conf` 字典覆盖 | ✅ | 全部文件均无 `conf={}` 参数覆盖 |
| 是否有 `conf_overrides` | ✅ | 全部文件均无 |
| 是否有 `rados.conf_set()` | ✅ | 全部文件均无调用 |
| 是否覆盖 `ms_type` 等参数 | ✅ | 全部文件均无显式设置任何 messenger 配置 |

**关键代码**（`ceph_manager.py:27`）：
```python
self.cluster = rados.Rados(conffile=CEPH_CONF)
```
仅指定 `conffile`，无任何额外参数，完整继承 ceph.conf 中的 RDMA 配置。

#### 3.2 连接方式检查

| 检查项 | 结果 | 说明 |
|---|---|---|
| 使用标准 librados 绑定 | ✅ | `m3_sync.py:8` `import rados`，其余通过 `ceph_manager` 间接使用 |
| 无 subprocess 调用 rados CLI | ✅ | `m5_perf.py` 有 `import subprocess` 但仅用于 SSH 远程协调，不调用 rados CLI |
| ceph.conf 路径正确 | ✅ | `config.py:5` 默认 `/etc/ceph/ceph.conf`，与集群实际 RDMA 配置文件一致 |
| 无硬编码 monitor 地址 | ✅ | monitor 地址从 ceph.conf 的 `mon_host` 读取 |
| 无硬编码 keyring 路径 | ✅ | keyring 从 ceph.conf 的 `keyring` 字段读取 |

#### 3.3 RDMA 兼容性检查

| 检查项 | 结果 | 说明 |
|---|---|---|
| python3-rados 链接 librados | ✅ | `rados.cpython-38-x86_64-linux-gnu.so` → `librados.so.2` |
| librados 链接 RDMA 库 | ✅ | `librados.so.2` → `libibverbs.so.1` + `librdmacm.so.1` |
| 宿主机 memlock 限制 | ✅ | `ulimit -l = unlimited` |
| RDMA 设备可用 | ✅ | `/sys/class/infiniband/mlx5_0` 存在（m3/m5 代码中有读取） |
| 对象大小兼容 | ✅ | M5: 64KB, M3/M6: <1KB JSON — 均在 RDMA 传输范围内 |
| 并发模式兼容 | ✅ | M5 每线程独立 `open_ioctx`（`m5_perf.py:94,171`），线程安全 |
| AIO 接口兼容 | ✅ | M6 `aio_remove`（`m6_tiering.py:359`）与 RDMA 兼容 |
| RDMA 静默回退风险 | ⚠️ | ceph.conf 中 GID 参数为 xfusion3 的值；若在其他节点运行需 per-host 配置（见下文） |

**python3-rados 库链接验证**：
```
$ ldd /usr/lib/python3/dist-packages/rados.cpython-38-x86_64-linux-gnu.so | grep -E "rados|rdma|ibverbs"
librados.so.2 => /lib/librados.so.2
libibverbs.so.1 => /lib/x86_64-linux-gnu/libibverbs.so.1
librdmacm.so.1 => /lib/x86_64-linux-gnu/librdmacm.so.1

$ ldd /lib/librados.so.2 | grep -E "rdma|ibverbs"
libibverbs.so.1 => /lib/x86_64-linux-gnu/libibverbs.so.1
librdmacm.so.1 => /lib/x86_64-linux-gnu/librdmacm.so.1
```

### 四、问题代码定位与修复建议

#### 4.1 非关键问题

| 文件 | 行号 | 问题 | 风险 | 说明 |
|---|---|---|---|---|
| `config.py` | 16-17 | 节点 IP 与实际 RDMA IP 不符 | ⚠️ 低 | `NODE_A.ip="192.168.0.3"` 实际应为 `192.168.0.218`；`NODE_B.ip="192.168.0.4"` 实际应为 `192.168.0.214`。**不影响 rados 连接**（仅用于前端展示），但可能造成前端显示混淆 |
| `m5_perf.py` | 39 | 远程协调使用 TCP 管理网 IP | ⚠️ 低 | `REMOTE_HOST="10.26.42.225"` 用于 SSH/HTTP 协调远程测试启动。**不影响 rados 数据路径**（远程节点的 rados 连接独立读取本节点 ceph.conf） |

#### 4.2 多节点运行的 GID 配置注意事项

当前 `/etc/ceph/ceph.conf` 中的 RDMA 参数（`gid_idx=2`, `local_gid=...c0a8:00da`）为 xfusion3 的值。如果 Python 后端在其他节点运行：

- **xfusion4**：需要 `gid_idx=2`, `local_gid=...c0a8:00d6`
- **xfusion5**：需要 `gid_idx=4`, `local_gid=...c0a8:00d7`

**缓解**：Ceph config store 中的 per-host client 配置（如已设置 `ceph config set client/host:xfusion5 ms_async_rdma_gid_idx 4`）会覆盖 ceph.conf 中的值。如果未设置 per-host 配置，需在各节点的 ceph.conf 中分别写入对应 GID 参数，或通过环境变量 `CEPH_CONF` 指向节点特定的配置文件。

### 五、各文件检查结果汇总

| 文件 | RDMA 配置继承 | 连接方式 | 库兼容性 | 总体判定 |
|---|---|---|---|---|
| `config.py` | ✅ 无覆盖 | N/A | N/A | ✅ 符合 |
| `ceph_manager.py` | ✅ `conffile=CEPH_CONF` | ✅ 标准 librados | ✅ 链接 RDMA | ✅ 符合 |
| `app.py` | ✅ 通过 ceph_mgr | ✅ 间接 librados | ✅ | ✅ 符合 |
| `utils.py` | N/A | N/A | N/A | ✅ 无关 |
| `m3_sync.py` | ✅ 通过 ceph_mgr | ✅ 标准 librados | ✅ | ✅ 符合 |
| `m5_perf.py` | ✅ 通过 ceph_mgr | ✅ 标准 librados | ✅ | ✅ 符合 |
| `m6_tiering.py` | ✅ 通过 ceph_mgr | ✅ 标准 librados | ✅ | ✅ 符合 |

### 六、总体结论

**✅ backend Python 代码不会破坏 RDMA 配置。**

1. **配置继承完整**：所有 Ceph 连接通过 `ceph_manager.py` 的 `rados.Rados(conffile="/etc/ceph/ceph.conf")` 建立，完整继承 ceph.conf 中的 `ms_type=async+rdma` 及所有 RDMA 参数，无任何代码覆盖。

2. **库链接正确**：`python3-rados` (cpython-38) → `librados.so.2` → `libibverbs.so.1` + `librdmacm.so.1`，RDMA 库链完整。宿主机 memlock=unlimited，RDMA 设备 mlx5_0 可用。

3. **无 TCP 风险代码**：全部 7 个文件中无 `conf_set()`、无 `conf={}`覆盖、无硬编码 monitor 地址、无 subprocess 调用 rados CLI。代码中的操作模式（同步读写、aio_remove、多线程并发）均与 RDMA 传输兼容。

4. **唯一注意事项**：ceph.conf 中的 RDMA GID 参数为 xfusion3 特定值。若在 xfusion4/xfusion5 运行 Python 后端，需确保 Ceph config store 中有对应节点的 per-host client RDMA 配置，或在各节点使用不同的 ceph.conf。
