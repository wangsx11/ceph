# PowerLeader2 + xfusion5 迁移说明

记录时间：2026-05-31

## 目标

当前项目最初是按 `xfusion3 + xfusion4` 这套拓扑搭起来的。现在要切换成：

- A 节点：`PowerLeader2`
- B 节点：`xfusion5`

你后续会把代码和数据同步到这两台机器上，并让 `PowerLeader2` 作为主节点发起启动、验证和演示。

## 结论

核心数据面代码不用重写。迁移主要是四类工作：

1. 节点配置从 `xfusion3 / xfusion4` 改成 `PowerLeader2 / xfusion5`
2. 启动脚本和控制面里写死的默认主机名改掉
3. 功能/性能脚本里默认的 peer、SSH probe、恢复命令改掉
4. 结果文档和 `raw.json / summary.md / history` 里的旧拓扑内容要刷新

如果你只想临时跑通，也可以先靠环境变量覆盖；如果你希望“不加参数也能直接跑”，就要把下面这些默认值一起改掉。

## 必改项

### 1. 节点配置

文件：

- `native_rdma/deploy/node_a.env`
- `native_rdma/deploy/node_b.env`

要改的内容：

- `SELF_IP`
- `PEER_IP`
- `GID_IDX`
- `RDMA_DEV`
- `NUMA_NODE`
- `HDD_PATH`
- `DRAM_CAP_BYTES`
- `NVME_CAP_BYTES`
- 如果现场网卡/交换机有变化，还要检查 `DATA_PORT`、`TCP_DATA_PORT`

建议：

- `node_a.env` 直接对应 `PowerLeader2`
- `node_b.env` 直接对应 `xfusion5`
- A 节点如果没有 GPU，不影响常规功能演示；`NR_GDR_ENABLE=0` 保持默认即可
- B 节点 `xfusion5` 需要在做 GPU Direct RDMA 相关功能时具备 GPU、CUDA、`nvidia_peermem`/`nv_peer_mem`

### 2. 启动与停止脚本

文件：

- `native_rdma/start.sh`
- `native_rdma/stop.sh`
- `native_rdma/scripts/demo_up.sh`

要改的内容：

- `PEER_HOST` 默认值从 `xfusion4` 改成 `xfusion5`
- 如果脚本注释里还写着 `xfusion3 / xfusion4`，也要同步改成新拓扑
- 如果 `PowerLeader2` 和 `xfusion5` 的仓库路径不完全一致，要显式设置 `PEER_REPO_ROOT`

说明：

- `start.sh` 会做本地构建、rsync 到 peer、远端构建、再启动双节点
- 这个流程默认就是“主节点同步到 peer”，所以 `PowerLeader2` 作为 A 节点最适合

### 3. 控制面默认值

文件：

- `native_rdma/control_plane/app.py`

要改的默认值：

- `_PERFORMANCE_DEFAULT_ENV["PERF_SSH_PROBE_HOST"]`：现在默认是 `xfusion4`
- `_sanitize_function_env()` 里 `mempool/FN-6` 的默认 `PEER_SSH`
- `FN6_RECOVERY_CMD` 里写死的 `LOCAL_HOST=xfusion3`

原因：

- 前端点“运行”时会走这里的默认配置
- 不改的话，功能/性能页面会继续拿旧主机名做 SSH 探测和恢复

### 4. 功能批量/恢复脚本默认值

文件：

- `functions/run_all.py`

要改的默认值：

- `PEER_SSH=xfusion4`
- `FN6_RECOVERY_CMD=cd native_rdma && LOCAL_HOST=xfusion3 ...`

说明：

- `mempool/FN-6` 需要主动拉起 peer、再恢复 peer
- 这里如果不改，仍然会默认连旧机器

### 5. 性能批处理默认探测主机

文件：

- `performances/run_all.sh`

要改的默认值：

- `PERF_SSH_PROBE_HOST=xfusion4`

说明：

- 性能跑分里会对 peer 做前置 SSH probe
- 不改默认值，性能页面会继续探测 `xfusion4`

### 6. 功能检查逻辑里的旧主机名

文件：

- `functions/common/checks.py`
- `functions/common/catalog.py`

要改的内容：

- 错误提示、说明文字里写死的 `xfusion3 / xfusion4`
- GDR 检查里默认的 `peer_host`
- 相关功能说明里的节点名描述

说明：

- 这部分不一定影响运行，但会影响前端展示、summary 和验收口径
- 如果你后面要正式演示，最好同步刷新，不然页面里会一直冒出旧拓扑名字

## 需要刷新但不一定要改代码的内容

### 1. 结果文件

这些文件里会直接记录旧节点名和旧拓扑证据：

- `functions/*/raw.json`
- `functions/*/summary.md`
- `functions/*/history/**`
- `performances/*/raw.json`
- `performances/*/summary.md`
- `performances/*/history/**`

如果你只是把仓库同步到新机器，但不重新跑一遍，前端仍可能展示旧的 `xfusion3 / xfusion4` 字样。

### 2. 文档和展示材料

下面这些文档大概率也会提到旧拓扑，迁移后最好一并刷新：

- `docs/硬件配置.md`
- `docs/会话.md`
- `docs/function_dashboard验证与实现文案.md`
- `docs/功能测试视频展示文案.md`
- `docs/功能要求实现完整性检查.md`
- `docs/性能原始结果解读.md`

## 推荐同步方式

如果 `PowerLeader2` 和 `xfusion5` 都能直接访问 Git 远端，优先用同一个分支同步：

```bash
git fetch origin
git checkout native_rdma
git pull --ff-only origin native_rdma
```

建议两台机器都保持同一个目录名，比如：

```text
/home/wangshouxin/native-rdma-web
```

这样 `start.sh` 里的 peer 同步路径最少要改。

## 推荐验证顺序

1. 确认 `ssh PowerLeader2` / `ssh xfusion5` 都可用
2. 确认两端 `show_gids`、`ibv_devinfo`、`ip -br addr`
3. 确认 A/B 节点 RDMA 直连或同网段可互通
4. 确认 `PowerLeader2` 到 `xfusion5` 的免密 SSH
5. 先跑 `bash native_rdma/start.sh`
6. 再跑关键功能项和关键性能项

## 最小可先验证的点

- `functions/rdma/FN-1`
- `functions/rdma/FN-4`
- `functions/mempool/FN-6`
- `performances/PF-2`
- `performances/PF-4`
- `performances/PF-6`

## 一句话总结

这次迁移的本质不是重写算法，而是把项目里所有“默认的旧节点名、旧路径、旧探测目标”换成 `PowerLeader2 + xfusion5`，然后把最新代码和最新结果重新同步一遍。
