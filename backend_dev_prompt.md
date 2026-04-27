# Codex 任务 Prompt — 后端功能实现与性能优化

请读取 `docs/演示要求.md` 和 `docs/性能要求.md`，了解需要实现的完整功能和性能指标，然后按照以下规范开始执行任务。

---

## 环境说明

- **xfusion3**（当前节点，Node A）：`CURRENT_NODE=A PORT=5000 python3 app.py`
- **xfusion4**（Node B）：ssh 登录后在同名目录下执行 `CURRENT_NODE=B PORT=5000 python3 app.py`
- 两台机器需要协同工作，每次代码修改后必须先同步到 xfusion4 再启动验证。

## 集群权限说明

- 该环境为个人独占使用，可对系统进行任何必要操作。
- **但凡需要使用 `sudo` 的操作，必须在执行前向我明确声明**，说明具体命令和原因，等待确认后再执行，不得静默使用 `sudo`。

---

## 准备工作（开始前必须完成）

### 1. 备份现有后端

```bash
cp -r ~/ceph-web/backend ~/ceph-web/backend_backup_$(date +%Y%m%d_%H%M%S)
```

### 2. 创建工作目录

在 `~/ceph-web/` 下新建 `backend_dev/` 作为本次所有修改的工作目录，**不要直接修改原始 `backend/`**。

### 3. 初始化尝试记录文档

在 `~/ceph-web/` 下创建 `dev_log.md`，用于记录每次尝试方案，格式见下方【尝试记录规范】。

---

## 执行流程

### 第一步：读取需求

完整阅读以下两个文档，提取所有功能点和性能指标：
- `docs/演示要求.md` — 功能列表与演示场景
- `docs/性能要求.md` — 延迟、吞吐量、IOPS 等具体指标

阅读完毕后，在 `dev_log.md` 开头整理出一张需求清单，格式如下：

```markdown
## 需求清单

### 功能点
- [ ] 功能 1
- [ ] 功能 2
...

### 性能指标
- 指标 1：要求 >= X
- 指标 2：要求 <= Y
...
```

### 第二步：系统环境检查

在动代码之前，先检查底层系统是否满足性能要求的基础条件，包括但不限于：

```bash
# 网络带宽与延迟
ping xfusion4
ib_send_bw && ib_write_bw   # RDMA 带宽
ib_send_lat                  # RDMA 延迟

# 磁盘性能
fio --filename=/dev/sdX --rw=randread --bs=4k --iodepth=32 --numjobs=4

# 系统资源
nproc && free -h && df -h

# Ceph 集群状态
ceph status && ceph osd perf
```

将检查结果记录到 `dev_log.md` 的【环境基线】章节，与 `docs/性能要求.md` 中的指标对照，提前判断哪些指标存在达标风险。

### 第三步：功能实现与验证循环

**每个功能点严格按此循环执行：**

```
① 分析需求，制定实现方案，记录到 dev_log.md
② 在 backend_dev/ 下修改代码
③ 同步到 xfusion4：
   rsync -avz ~/ceph-web/backend_dev/ wangshouxin@xfusion4:~/ceph-web/backend_dev/
④ 启动两端服务（先停掉旧进程）：
   - xfusion3: CURRENT_NODE=A PORT=5000 python3 backend_dev/app.py
   - xfusion4: ssh xfusion4 "cd ~/ceph-web && CURRENT_NODE=B PORT=5000 python3 backend_dev/app.py"
⑤ 验证功能完整性（对照 docs/演示要求.md 逐项检查）
⑥ 验证性能指标是否达标（对照 docs/性能要求.md 逐项测量）
⑦ 判断结果：
   - 功能 + 性能均达标 → 勾选需求清单对应条目，记录成功方案，继续下一个功能点
   - 未达标 → 执行【未达标处理】，返回 ②
```

### 未达标处理

1. 停止两端服务。
2. 分析根本原因，区分以下层面：
   - **代码层面**：算法、并发、数据结构等
   - **系统层面**：网络参数、磁盘调度器、内核参数、RDMA 配置、Ceph 调优等
3. 将本次尝试完整记录到 `dev_log.md`（格式见下方）。
4. 制定下一轮方案，返回循环 ②。
5. 若同一功能点**连续失败 3 次**，在 `dev_log.md` 中标注 `需人工介入`，跳过该功能点继续推进其他项。

---

## 尝试记录规范

每次尝试在 `dev_log.md` 中追加以下内容：

```markdown
## 尝试 N — YYYY-MM-DD HH:MM

### 目标
<本次要实现或优化的功能/性能点>

### 方案描述
<改了什么，为什么这样改；若涉及系统层面，说明调整了哪些参数>

### 系统层面检查（如有）
<内核参数、RDMA 配置、磁盘调度器、Ceph 配置等检查或调整结果>

### 测试输出
<功能验证结果 + 性能实测数据>

### 与性能要求对照
<逐项列出实测值 vs 要求值，标注达标 / 未达标>

### 结论
<整体达标 / 未达标，未达标的具体原因分析及下一步方向>
```

---

## 收尾规范

所有功能和性能均验证通过后：

1. 将 `backend_dev/` 的最终版本同步回 `backend/`：
   ```bash
   rsync -avz --delete ~/ceph-web/backend_dev/ ~/ceph-web/backend/
   ```
2. 执行全量同步到 xfusion4：
   ```bash
   rsync -avz --delete ~/ceph-web/ wangshouxin@xfusion4:~/ceph-web/
   ```
3. 在 `dev_log.md` 末尾写入最终总结：

```markdown
## 最终总结 — YYYY-MM-DD

### 已实现功能
- [x] 功能 1
- [x] 功能 2

### 性能达标情况
| 指标 | 要求 | 实测值 | 结论 |
|------|------|--------|------|
| ...  | ...  | ...    | 达标 |

### 未解决项
- 功能 X：需人工介入（原因：...）
```

---

现在开始，先完成准备工作，再依次读取 `docs/演示要求.md` 和 `docs/性能要求.md`，整理需求清单后按上述流程逐步推进。