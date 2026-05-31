# 原版备份策略变更与远端同步说明

记录时间：2026-05-31

## 背景

此前计划把 A 节点从 `xfusion3` 切换到 `xfusion5`，B 节点仍使用 `xfusion4`。当时为了避免迁移过程中 `xfusion5` 和 `xfusion4` 的 `native_rdma` 代码不适配，曾从 `xfusion4` 打包保留了一份原版 `native_rdma` 快照。

现在需求已经变更：

- A 节点：`PowerLeader2`
- B 节点：`xfusion5`
- `xfusion5` 当前可通过 `ssh xfusion5` 访问。
- `PowerLeader2` 通过 `ssh wangshouxin@10.26.42.216` 访问。

后续不再以 `xfusion4` 原版 `native_rdma` 压缩包作为主要保护手段，而是将当前代码和必要结果数据推送到 Git 远端。这样后续在 PowerLeader2 或 xfusion5 上部署时，以远端仓库为统一来源，避免多个手工备份版本互相混淆。

注意：账号密码等敏感信息不写入仓库、文档和脚本。

## 当前状态

当前仓库远端：

```text
origin git@github.com:wangsx11/ceph.git
branch native_rdma
```

当前新拓扑还没有完成实测验证。正式演示前仍必须确认：

- PowerLeader2 是否具备可用 RDMA 网卡和 RoCE IP。
- PowerLeader2 与 xfusion5 是否能通过 RDMA 口直连或同网段互通。
- PowerLeader2 和 xfusion5 的 `show_gids` 输出，并据此设置各自 `GID_IDX`。
- xfusion5 是否满足 B 节点 GPU Direct RDMA 前置条件：
  - NVIDIA GPU 可用。
  - CUDA 可用。
  - `nvidia_peermem` 或 `nv_peer_mem` 已加载。
  - RDMA 设备可用，通常为 `mlx5_0`。
- PowerLeader2 到 xfusion5 的 SSH 免密是否可用。当前 `native_rdma/start.sh` 依赖主节点 SSH 到 peer 做同步、构建和启动。

## 旧备份情况

此前曾生成过：

```text
/home/wangshouxin/native-rdma-web/backups/native_rdma_xfusion4_20260530.tar.gz
```

这份压缩包只是 `xfusion4` 旧拓扑下的原版快照。现在切换到 `PowerLeader2 + xfusion5` 后，它不再是主恢复路径。

处理建议：

- 可以暂时保留本地文件作为历史参考。
- 不建议提交或依赖这份 tar 包作为正式迁移方案。
- 如果远端仓库已经包含当前代码和结果数据，后续优先从 Git 远端恢复。

## 本次要做的事情

1. 更新本说明文档，记录拓扑从 `xfusion5 + xfusion4` 变更为 `PowerLeader2 + xfusion5`。
2. 将当前代码和必要结果数据提交到 Git。
3. 推送到远端 `origin/native_rdma`。
4. 不把密码、临时大日志、历史目录和备份 tar 作为迁移依赖。

## 后续部署建议

### 1. 在 PowerLeader2 上拉取代码

```bash
cd /home/wangshouxin
git clone -b native_rdma git@github.com:wangsx11/ceph.git native-rdma-web
```

如果目录已存在：

```bash
cd /home/wangshouxin/native-rdma-web
git fetch origin
git checkout native_rdma
git pull --ff-only origin native_rdma
```

### 2. 在 xfusion5 上同步代码

如果 xfusion5 作为 B 节点，由 PowerLeader2 运行 `native_rdma/start.sh` 时会自动 rsync 当前仓库到 peer。也可以先手工在 xfusion5 上拉取同一分支：

```bash
cd /home/wangshouxin
git clone -b native_rdma git@github.com:wangsx11/ceph.git native-rdma-web
```

### 3. 修改节点配置

需要根据现场 `ip -br addr` 和 `show_gids` 输出重新设置：

```text
native_rdma/deploy/node_a.env
native_rdma/deploy/node_b.env
```

原则：

- `node_a.env` 对应 PowerLeader2。
- `node_b.env` 对应 xfusion5。
- 两边 `SELF_IP` / `PEER_IP` 必须互相指向对方 RDMA IP。
- 两边 `GID_IDX` 必须使用本机 `show_gids` 中对应 RoCE IPv4 v2 的 index。
- B 节点 xfusion5 需要保留 GPU/GDR 相关能力。

### 4. 验证顺序

正式跑功能前，先做最小验证：

```bash
ip -br addr
show_gids
ibv_devinfo
ping <peer-rdma-ip>
```

然后再跑裸 RDMA：

```bash
ib_write_bw
ib_write_lat
```

最后启动项目：

```bash
cd /home/wangshouxin/native-rdma-web/native_rdma
bash start.sh
```

建议最小功能/性能验证集：

```text
functions/rdma/FN-1
functions/rdma/FN-4
functions/mempool/FN-6
performances/PF-2
performances/PF-6
```

## 恢复方式

后续如果某台机器上的目录被改乱，优先使用 Git 远端恢复：

```bash
cd /home/wangshouxin/native-rdma-web
git fetch origin
git checkout native_rdma
git pull --ff-only origin native_rdma
```

如果需要完全重建：

```bash
cd /home/wangshouxin
mv native-rdma-web native-rdma-web.bak_$(date +%Y%m%d_%H%M%S)
git clone -b native_rdma git@github.com:wangsx11/ceph.git native-rdma-web
```

旧的 xfusion4 tar 包只作为历史参考，不作为新拓扑的首选恢复手段。
