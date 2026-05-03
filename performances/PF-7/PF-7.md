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
- 当前环境可看到 MR9560-8i RAID 控制器暴露的块设备，但未确认 RAID level 和成员盘数量前，只能作为当前存储路径写入延迟测试，不能作为严格 3+1 RAID5 验收。
- 默认口径建议为 4KB 随机写，direct I/O 优先，队列深度 1，单线程，测试时长不少于 60 秒。
- 默认不对每个请求执行 fsync；如启用 fsync，必须在结果中单独标注。

## 交互

1. 确认 RAID 拓扑和测试路径，记录到结果摘要。
2. 设置可选参数：
   ```bash
   export BACKUP_TEST_PATH=/path/on/raid5
   export DUR=60
   export THREADS=1
   export QUEUE_DEPTH=1
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
- 默认访问模式为随机写。
- 默认 direct I/O 优先；平台不支持时必须在结果中标注。
- 默认队列深度为 1，线程数为 1，测试时长不少于 60 秒。
- P999 按成功写入请求时延样本计算。
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
