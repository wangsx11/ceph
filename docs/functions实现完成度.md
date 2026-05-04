# functions 实现完成度

## 当前结论

- 更新时间：2026-05-04
- 总体进度：基本完成
- 当前阶段：已完成 `functions/` 功能测试框架与 17 个功能点入口；RDMA FN-4 已补齐真实 GPU Direct RDMA 闭环；mempool FN-1/FN-2/FN-3/FN-4/FN-5/FN-6 已补齐 C++ 数据面运行态证据。
- 关键复核记录：
  - `mempool/FN-1` 旧 summary 为 `SKIP`，原因是 peer 不在线，且旧脚本只检查 `repl_ns/degraded`，未强制 RDMA transport 和 peer 读回。已增强 C++ `RPC_CLUSTER_STATUS` 的 slab 元数据字段并收紧脚本，2026-05-04 15:11 已在双节点重跑 PASS：`RPC_KV_PUT_RDMA transport=rdma degraded=false repl_ns=67264`，peer slab `base/len/rkey/qps` 有效，`offset=2093056 size=20` 落在 peer slab 范围内，`RPC_TCP_GET_PEER` 读回同值。
  - `mempool/FN-2` 旧 summary 只证明本地 `PUT -> GET`，且 `degraded=true` 仍 PASS，不能证明分布式 API 的 peer 副本。已收紧脚本，2026-05-04 15:17 双节点重跑 PASS：普通 `RPC_KV_PUT transport=rdma degraded=false repl_ns=35615`，本地/peer slab 元数据有效，`offset=3141632 size=26` 同时落在两端 slab 范围内，本地 `RPC_KV_GET` 与 `RPC_TCP_GET_PEER` 均读回 `distributed-pool-api-value`。
  - `mempool/FN-3` 旧 summary 为 `SKIP`，原因是 `REQUIRE_PEER=1` 且 `peer_alive=false`，且旧脚本只看 peer slab 字段，不能证明 PoolRegistry 统一命名。已新增 `RPC_MEMPOOL_POOLS` 并收紧脚本，2026-05-04 15:26 双节点重跑 PASS：local/remote 均登记为 `default/slab1k`，本地 registry 与 `RPC_CLUSTER_STATUS` 的 slab base/len/lkey/rkey 一致，远端 registry 与 OOB peer slab base/len/rkey 一致。
  - `rdma/FN-1` 已收紧验收脚本：默认 `REQUIRE_PEER=1` 时必须当前 `peer_alive=true`，并且只扫描最近一次数据面启动日志。已新增 TCP data channel，并要求 `NR_TRANSPORT=tcp NR_ASYNC_REPL=0` 下普通 `RPC_KV_PUT` 走 TCP 复制，再用 `RPC_TCP_GET_PEER` 证明传统 TCP/IP 数据传输闭环；同时采集 `RPC_KV_PUT_RDMA` 与 TCP 普通 PUT 的同步复制时延 avg/p50/p95。2026-05-04 13:21 已在双节点手动重跑 PASS。
  - `rdma/FN-2` 旧 summary 在 `peer_alive=false` 时仍 PASS，只能证明本地批量写。已增强 C++ 批量 RPC 和验收脚本，并于 2026-05-04 13:48 以 `bash start.sh` 默认 RDMA transport 和同步复制模式双节点重跑 PASS：`ok_n=8/8`、`replicated_n=8/8`、`degraded_n=0`、`repl_failed_n=0`、peer 读回 8/8 同值。
  - `rdma/FN-3` 旧 summary 在 `peer_alive=false` 时仍 PASS，且 HI/LO PUT 均为 `degraded=true`，只能证明本地降级写。已增强 C++ PUT 响应和验收脚本，并于 2026-05-04 14:00 双节点重跑 PASS：HI 走 RDMA QP 0、LO 走 RDMA QP 16，均 `degraded=false`，peer 读回同值。
  - `rdma/FN-5` 旧 summary 只证明 `RPC_ROUTE_QUERY` 的一致性哈希分布，不证明真实转发。已新增 `RPC_ROUTE_PUT` 和验收脚本，并于 2026-05-04 14:07 双节点重跑 PASS：64 个 key primary 覆盖两个节点，本地 primary 未转发且本地读回，远端 primary 经 TCP data channel 转发到 peer 并读回。
  - `rdma/FN-4` 已新增 CUDA/GPU Direct 数据面、OOB GPU MR 元数据交换和 `RPC_GDR_*` 验收，并于 2026-05-04 14:46 双节点重跑 PASS：xfusion4 GPU MR 有效，A->B RDMA WRITE 写入 GPU 显存，B 端 CUDA kernel 校验通过，A 端 RDMA READBACK 校验通过。
  - `storage/FN-4` 已新增运行时去重 RPC/统计闭环，并已重跑生成 PASS 证据。
  - `storage/FN-6` 已增强为 WAL 文件解析和 ObjectAttr/InteractionEvent 类型校验，并已在 `2026-05-04T12:16:58+0800` 重跑生成 PASS 证据。
  - `mempool/FN-4` 旧 summary 虽为 PASS，但只证明存储层 `TierEngine` demote 到 NVMe 后读时提升，且旧 PUT 为 `degraded=true`，不等同于跨节点远端/本地内存自适应放置。已新增 `RPC_MEMPOOL_ADAPT_PUT/GET/STATS` 并收紧脚本，2026-05-04 15:41 双节点重跑 PASS：冷对象 RDMA WRITE 到 peer slab，首次访问保持远端 RDMA READ，访问计数达到热点阈值 3 后 RDMA READ 迁回本地 slab，随后普通 `RPC_KV_GET hit=local`。
  - `mempool/FN-5` 旧脚本只验证单 tenant 的 ACL 拒绝/允许/撤销，未证明不同任务/用户使用同一逻辑 key 时具备独立内存空间。已新增非默认 tenant 内部 key 命名空间隔离并收紧脚本，2026-05-04 15:50 重跑 PASS：tenant A/B 同一逻辑 key 分别写入不同 value，读回各自 value；撤销 A 后 A 被拒绝，B 仍可读；最终 `RPC_ISO_LIST` 只保留默认租户。
  - `mempool/FN-6` 旧脚本默认只做非破坏性 HA 字段检查，未执行 peer 故障降级闭环。已收紧为主动故障演练并在 2026-05-04 16:03 双节点重跑 PASS：演练前 `peer_alive=true`；kill xfusion4 数据面后 xfusion3 观测 `peer_alive=false`；故障期间 `RPC_KV_PUT ok=true degraded=true transport=rdma`，本地 `RPC_KV_GET hit=local` 读回同值，`degraded_puts 0->1`、`degraded_bytes 0->29`；恢复 `start.sh` 后 `peer_alive=true`，后续 PUT `degraded=false transport=rdma` 并可从 peer 读回。

## 根目录进度

| 项目 | 状态 | 说明 |
|---|---|---|
| functions/ | 完成 | 已创建目录骨架 |
| functions/common/ | 完成 | 已实现公共 UDS、HTTP、日志、summary 与判定逻辑 |
| functions/run_all.sh | 完成 | 已实现总入口 Bash 封装 |
| functions/run_all.py | 完成 | 已实现聚合执行与总 summary；2026-05-04 修正为存在 `FAIL` 或 `SKIP` 时总结果为 `FAIL` |
| functions/summary.md | 完成 | 已创建初始文件，后续由 run_all 覆盖 |

## 功能点进度

| 模块 | 功能点 | 状态 | 脚本 | 最近验证 | 说明 |
|---|---|---|---|---|---|
| storage | FN-1 | 完成 | 已生成 | PASS | 异构存储统一访问接口 |
| storage | FN-2 | 完成 | 已生成 | PASS | 多层感知与冷热分离 |
| storage | FN-3 | 完成 | 已生成 | PASS | 多策略预取 |
| storage | FN-4 | 完成 | 已生成 | PASS | `RPC_COMPRESS_STATS` 证明冷层压缩，`RPC_DEDUP_STATS` 证明重复对象运行时去重，两个对象均 `hdd_promote` 读回 |
| storage | FN-5 | 完成 | 已生成 | PASS | `RPC_IO_STATS` 证明 NVMe 前台 FG 与 HDD 后台 BG 读写计数均增加，并完成对象读回 |
| storage | FN-6 | 完成 | 已生成 | PASS | `RPC_SIM_CAPTURE_STATS` 证明 ObjectAttr=100、InteractionEvent=100；WAL 解析 events=200、bytes=11200、无截断 |
| rdma | FN-1 | 完成 | 已生成 | PASS | 2026-05-04 13:21 双节点验证通过：`peer_alive=true`、普通 `RPC_KV_PUT transport=tcp degraded=false`、`RPC_TCP_GET_PEER` 同值读回；RDMA/TCP 同步复制时延：RDMA avg=23.005us p95=21.657us，TCP avg=199.431us p95=215.146us |
| rdma | FN-2 | 基本完成 | 已生成 | PASS | 2026-05-04 13:48 双节点验证通过：`peer_alive=true`、`transport=rdma`、`async_repl=false`；`RPC_KV_PUT_BATCH ok_n=8/8 replicated_n=8/8`，`degraded_n=0`、`repl_failed_n=0`，`RPC_TCP_GET_PEER 8/8` 同值读回 |
| rdma | FN-3 | 基本完成 | 已生成 | PASS | 2026-05-04 14:00 双节点验证通过：`peer_alive=true`、`transport=rdma`、`async_repl=false`；HI 走 RDMA QP 0、LO 走 RDMA QP 16，均 `degraded=false`，peer 读回同值 |
| rdma | FN-4 | 完成 | 已生成 | PASS | 2026-05-04 14:46 双节点验证通过：xfusion4 NVIDIA GPU/CUDA/nvidia_peermem/mlx5_0 可用；peer GPU MR `len=67108864`、`rkey=87283` 有效；A->B `RPC_GDR_WRITE` 写入 GPU MR 4096B `write_ns=57671`；B 端 CUDA kernel 校验 `mismatches=0 checksum=522240`；A 端 `RPC_GDR_READBACK` 读回校验通过 |
| rdma | FN-5 | 基本完成 | 已生成 | PASS | 2026-05-04 14:07 双节点验证通过：64 个 key primary 覆盖两个节点；本地 primary `route_forwarded=false` 并本地读回；远端 primary `route_forwarded=true forward_transport=tcp_data_channel` 并从 peer 读回 |
| mempool | FN-1 | 完成 | 已生成 | PASS | 2026-05-04 15:11 双节点验证通过：`RPC_KV_PUT_RDMA transport=rdma degraded=false repl_ns=67264`，peer slab 元数据有效，offset/size 在 peer slab 范围内，`RPC_TCP_GET_PEER` 从 peer 读回 `rdma-zero-copy-probe` |
| mempool | FN-2 | 完成 | 已生成 | PASS | 2026-05-04 15:17 双节点验证通过：普通 `RPC_KV_PUT transport=rdma degraded=false repl_ns=35615`，本地 `RPC_KV_GET` 和 peer `RPC_TCP_GET_PEER` 均读回同值 |
| mempool | FN-3 | 完成 | 已生成 | PASS | 2026-05-04 15:26 双节点验证通过：`peer_alive=true`、`transport=rdma`；`RPC_MEMPOOL_POOLS` 返回 local/remote 同名 `default/slab1k`，registry 元数据与 cluster/OOB slab base/len/lkey/rkey 一致 |
| mempool | FN-4 | 完成 | 已生成 | PASS | 2026-05-04 15:41 双节点验证通过：冷对象 `RPC_MEMPOOL_ADAPT_PUT placement=remote transport=rdma`，远端 peer 可读；第 1/2 次访问 `remote_rdma_read`，第 3 次热点访问 `remote_to_local_migrate`，随后普通 `RPC_KV_GET hit=local` |
| mempool | FN-5 | 完成 | 已生成 | PASS | 2026-05-04 15:50 验证通过：两个临时 tenant 未授权写入失败；授权后同一逻辑 key 分别读回各自 value；撤销后对应 tenant 访问失败，`RPC_ISO_LIST` 反映 ACL 变化 |
| mempool | FN-6 | 完成 | 已生成 | PASS | 2026-05-04 16:03 主动故障演练通过：kill xfusion4 后 xfusion3 `peer_alive=false`，故障 PUT `degraded=true` 且本地 GET 可读，`degraded_puts/degraded_bytes` 增加；恢复后 RDMA 非降级 PUT 并从 peer 读回 |

## 已执行验证

| 时间 | 命令 | 结果 | 说明 |
|---|---|---|---|
| 2026-05-03 | 读取 docs/project-onboarding-skill/SKILL.md | 完成 | 用户给出的 dosc 路径不存在，实际文件在 docs/ |
| 2026-05-03 | 读取 docs/功能指标拆分与functions目录需求.md | 完成 | 已按文档开始实现 |
| 2026-05-03 | 创建 functions/ 公共框架和 17 个 FN 目录 | 完成 | 已完成脚本、文档、summary 初始文件和运行日志目录 |
| 2026-05-03 | `python3 -m py_compile ...` | 通过 | 已检查公共 Python 与 17 个 `run.py` |
| 2026-05-03 | `bash -n functions/run_all.sh`、`bash -n functions/common/run_one.sh`、`bash -n functions/storage/FN-1/run.sh`、`bash -n native_rdma/tests/run_all_functional.sh` | 通过 | FN `run.sh` 使用同一模板 |
| 2026-05-03 | 通过 `ssh xfusion4` 启动 B 节点，通过 `ssh xfusion3` 启动 A 节点 | 完成 | 两端 `/api/cluster/status` 均显示 `peer_alive=true`、`rdma_connected=true` |
| 2026-05-03 | `bash functions/run_all.sh` | FAIL/部分完成 | 最近总汇总为 17 项：PASS 14、FAIL 0、SKIP 2、WAIVED 1；`mempool/FN-1`、`mempool/FN-3` 因 peer 不在线跳过 |
| 2026-05-04 | 静态复核 `functions/common/checks.py`、`functions/summary.md`、`native_rdma/data_plane/main.cpp` | 完成 | 确认多数功能测试直连 UDS/C++ 数据面；修正 `functions/run_all.py`，存在 SKIP 时不再输出总 PASS |
| 2026-05-04 | `bash functions/rdma/FN-1/run.sh` | SKIP | 已收紧 FN-1 判据后重跑；当前沙箱连接 `/tmp/native_rdma-dp.sock` 返回 `Operation not permitted`，未生成假 PASS |
| 2026-05-04 | `cmake --build native_rdma/build-current -j` | 通过 | 新增 TCP data channel 与 FN-1 TCP 复制闭环后，本地 C++ 构建通过 |
| 2026-05-04 | `bash functions/rdma/FN-1/run.sh` | SKIP | 新增普通 `RPC_KV_PUT` TCP 切换、`RPC_TCP_GET_PEER`、RDMA/TCP 同步复制时延对比后重跑；当前沙箱连接 `/tmp/native_rdma-dp.sock` 返回 `Operation not permitted`，需节点 A 正常环境以 `NR_TRANSPORT=tcp NR_ASYNC_REPL=0` 重跑 |
| 2026-05-04 13:21 | `NR_TRANSPORT=tcp NR_ASYNC_REPL=0 bash start.sh` 后执行 `bash functions/rdma/FN-1/run.sh` | PASS | 双节点显式 TCP/IP 切换闭环与 RDMA/TCP 同步复制时延对比已生成 summary/raw/log 证据 |
| 2026-05-04 | `cmake --build native_rdma/build-current -j` | 通过 | RDMA FN-2 批量 RPC 增加复制计数、同步复制结果检查和 peer index 更新；脚本增加双节点、同步 RDMA 与 peer 读回验收 |
| 2026-05-04 13:48 | `bash start.sh` 后执行 `bash functions/rdma/FN-2/run.sh` | PASS | 双节点批量小对象 RDMA 传输闭环通过：`ok_n=8/8`、`replicated_n=8/8`、peer 读回 8/8 同值 |
| 2026-05-04 | `cmake --build native_rdma/build-current -j` | 通过 | RDMA FN-3 PUT 响应增加 QoS priority/QP 分组字段；脚本增加双节点、同步 RDMA、HI/LO QP 分组和 peer 读回验收 |
| 2026-05-04 14:00 | `bash start.sh` 后执行 `bash functions/rdma/FN-3/run.sh` | PASS | 双节点流量优先级机制闭环通过：HI 走 QP 0、LO 走 QP 16，均 RDMA 非降级写并完成 peer 读回 |
| 2026-05-04 | `cmake --build native_rdma/build-current -j` | 通过 | RDMA FN-5 新增 `RPC_ROUTE_PUT`，脚本增加双节点、路由分布、本地/远端 primary routed PUT 和 peer 读回验收 |
| 2026-05-04 14:07 | `bash start.sh` 后执行 `bash functions/rdma/FN-5/run.sh` | PASS | 双节点路由转发与负载均衡闭环通过：64 个 key primary 覆盖两个节点，远端 primary 经 TCP data channel 转发到 peer 并读回 |
| 2026-05-04 | `cmake -S native_rdma -B native_rdma/build-current -DNR_USE_CUDA=OFF -GNinja && cmake --build native_rdma/build-current -j` | 通过 | xfusion3 本地 CUDA OFF 构建通过，避免无 GPU/无 CUDA 环境构建失败 |
| 2026-05-04 14:46 | `LOCAL_HOST=xfusion3 NR_GDR_ENABLE=1 NR_TRANSPORT=rdma NR_ASYNC_REPL=0 bash start.sh` 后执行 `REQUIRE_PEER=1 bash functions/rdma/FN-4/run.sh` | PASS | 双节点 GPU Direct RDMA 闭环通过：xfusion4 GPU/CUDA/nvidia_peermem 可用，B 端 `cudaMalloc` GPU buffer 注册为 RDMA MR，A 端 RDMA WRITE 到 B GPU MR，B 端 CUDA kernel 校验，A 端 RDMA READBACK 校验 |
| 2026-05-04 15:11 | `LOCAL_HOST=xfusion3 NR_TRANSPORT=rdma NR_ASYNC_REPL=0 bash start.sh` 后通过 `ssh xfusion3` 执行 `REQUIRE_PEER=1 bash functions/mempool/FN-1/run.sh` | PASS | 双节点 RDMA 远程内存访问闭环通过：`RPC_KV_PUT_RDMA transport=rdma degraded=false`，peer slab `base/len/rkey/qps` 有效，offset/size 范围正确，并从 peer 读回同值 |
| 2026-05-04 15:17 | 通过 `ssh xfusion3` 执行 `REQUIRE_PEER=1 bash functions/mempool/FN-2/run.sh` | PASS | 分布式内存池封装 API 闭环通过：普通 `RPC_KV_PUT` 走 RDMA 非降级写，本地 `RPC_KV_GET` 和 peer `RPC_TCP_GET_PEER` 均读回同值 |
| 2026-05-04 | `python3 -m py_compile functions/common/checks.py functions/common/runner.py functions/mempool/FN-3/run.py`、`bash -n functions/mempool/FN-3/run.sh`、`cmake --build native_rdma/build-current -j` | 通过 | FN-3 新增 `RPC_MEMPOOL_POOLS` 和 PoolRegistry/OOB 一致性检查后，Python/Bash/C++ 构建均通过 |
| 2026-05-04 15:26 | `LOCAL_HOST=xfusion3 NR_TRANSPORT=rdma NR_ASYNC_REPL=0 bash start.sh` 后通过 `ssh xfusion3` 执行 `REQUIRE_PEER=1 bash functions/mempool/FN-3/run.sh` | PASS | 内存池统一命名机制闭环通过：本地 pool 和远端 pool 均为 `default/slab1k`；local registry 与 cluster slab 元数据一致；remote registry 与 OOB peer slab 元数据一致 |
| 2026-05-04 | `python3 -m py_compile functions/common/checks.py functions/common/runner.py functions/mempool/FN-4/run.py`、`bash -n functions/mempool/FN-4/run.sh`、`cmake --build native_rdma/build-current -j` | 通过 | FN-4 新增远端优先放置、RDMA READ 热点本地化迁移和自适应统计 RPC 后，Python/Bash/C++ 构建均通过 |
| 2026-05-04 15:41 | `LOCAL_HOST=xfusion3 NR_TRANSPORT=rdma NR_ASYNC_REPL=0 bash start.sh` 后通过 `ssh xfusion3` 执行 `REQUIRE_PEER=1 bash functions/mempool/FN-4/run.sh` | PASS | 跨节点内存自适应分配与热数据迁移闭环通过：冷对象先落 peer slab，连续访问达到热点阈值后迁回本地 slab，普通 GET 本地命中 |
| 2026-05-04 | `python3 -m py_compile functions/common/checks.py functions/common/runner.py functions/mempool/FN-5/run.py`、`bash -n functions/mempool/FN-5/run.sh`、`cmake --build native_rdma/build-current -j` | 通过 | FN-5 新增 tenant 内部 key 命名空间隔离和双租户同名 key 验收后，Python/Bash/C++ 构建均通过 |
| 2026-05-04 15:50 | `LOCAL_HOST=xfusion3 NR_TRANSPORT=rdma NR_ASYNC_REPL=0 bash start.sh` 后通过 `ssh xfusion3` 执行 `bash functions/mempool/FN-5/run.sh` | PASS | 任务级与用户级隔离闭环通过：tenant A/B 同名 key 互不串读，撤销后访问被拒绝，ACL list 状态正确 |
| 2026-05-04 16:03 | `ALLOW_DESTRUCTIVE=1 REQUIRE_PEER=1 PEER_SSH=xfusion4 PEER_DP_PATH=/home/wangshouxin/native-rdma-web/native_rdma/build-current/bin/native_rdma_dp FN6_RECOVERY_CMD='cd native_rdma && LOCAL_HOST=xfusion3 NR_TRANSPORT=rdma NR_ASYNC_REPL=0 bash start.sh' bash functions/mempool/FN-6/run.sh` | PASS | 内存池高可靠主动故障演练通过：peer 故障期间本节点 degraded PUT 和本地 GET 继续可用，降级计数递增；恢复后重新 RDMA 非降级复制并完成 peer 读回 |
