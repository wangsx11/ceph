# PF-7 仿真引擎定期备份存储能力测试说明

## 功能点

- 性能点名称：仿真引擎定期备份存储能力。
- 来源指标：`docs/性能要求.md` 第 7 条。
- 现有参考脚本：待新增。
- 功能说明：验证备份存储路径在 3+1 RAID5 系统下处理 4KB 写入请求的尾延迟。

## 指标要求

- 存储前提：必须能确认测试路径位于 3+1 RAID5 系统上。
- 默认请求大小：4KB。
- 写入请求 P999 延迟 `lat_p999_us <= 1000us`。
- 需要报告 P50、P95、P99、P999、最大延迟和成功请求数。

## 测试方案

- 测试前通过 RAID 控制器工具或运维信息确认 RAID level、成员盘数量和测试挂载路径。
- 默认测试不绕过系统直接 fio 写文件，而是通过数据面 `RPC_BACKUP_WRITE` 执行 4KB 备份写入。
- 数据面普通 `RPC_KV_PUT` 热路径不等待备份写入完成，避免 PF-7 的严格备份语义影响 PF-1/PF-2 的 RDMA 小对象吞吐与端到端延迟。
- `RPC_BACKUP_WRITE` 写入独立的备份 ring 文件，返回数据面内部 `pwrite` 完成耗时；PF-7 根据该耗时计算 P50/P95/P99/P999。
- 默认不对每个请求执行 `fdatasync`；如启用 `BACKUP_FSYNC=1`，必须在结果中单独标注。
- `PF7_BACKEND=fio` 可切换为 fio 直写路径，仅用于存储设备对照测试，不作为默认数据面验收路径。
- 如果要指定 RAID5 路径，需要在启动数据面前设置 `BACKUP_PATH`，因为备份文件由 `native_rdma_dp` 打开和写入。

## 交互

1. 确认 RAID 拓扑和测试路径，记录到结果摘要。
2. 设置可选参数：
   ```bash
   export BACKUP_PATH=/path/on/raid5/pf7_backup.dat
   export DUR=60
   export THREADS=1
   export QUEUE_DEPTH=1
   export PF7_BACKEND=dataplane
   ```
3. 执行脚本：
   ```bash
   cd performances/PF-7
   bash run.sh
   ```
4. 查看结果：读取当前目录下的 `summary.md`，延迟样本或分位数原始输出固定写入当前目录。

## 实现

### 当前统计口径

- 默认请求大小为 4KB。
- 默认访问模式为数据面备份 ring 文件顺序覆盖写。
- 默认队列深度为 1，线程数为 1，测试时长不少于 60 秒。
- P999 按 `RPC_BACKUP_WRITE` 返回的成功写入时延样本计算。
- 失败请求不参与分位数，单独记录为 `failed_writes`，且验收要求 `failed_writes = 0`。
- 不统计脚本启动、文件预分配、环境探测和清理时间。

### 脚本入口

- Bash 入口：`performances/PF-7/run.sh`。
- Python 入口：`performances/PF-7/run.py`。
- 本次运行结果直接写入当前 `performances/PF-7/` 目录。

## 命令

```bash
cd performances/PF-7
bash run.sh
```
