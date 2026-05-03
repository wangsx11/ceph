# function_dashboard 功能验收前端设计方案

## 1. 目标

新增 `function_dashboard/` 前端，用于把 `functions/` 下已实现的 17 个功能验收项以页面形式展示，并支持在浏览器中点击按钮触发后台测试。

目标页面结构固定为：

```text
主页面
├── 左侧三个模块导航窗格
│   ├── 多级异构的高效能存储模块
│   ├── RDMA 分布式仿真计算模块
│   └── 一致性总线内存池化仿真计算模块
└── 右侧模块内容区
    ├── 顶部功能点跳转窗格
    └── 当前功能点详情区
        ├── 功能需求说明
        ├── 设计与实现说明
        ├── 一键启动测试
        ├── 测试结果展示
        └── 测试脚本展示
```

当前会话只产出方案文档，不实现代码。

## 2. 数据来源

前端展示和执行以现有 `functions/` 目录为准：

```text
functions/
├── run_all.sh
├── run_all.py
├── summary.md
├── raw.json
├── storage/FN-1..FN-6/
├── rdma/FN-1..FN-5/
└── mempool/FN-1..FN-6/
```

单个功能点的数据来源：

```text
functions/<module>/FN-N/
├── FN-N.md        # 功能需求、验证口径、实现位置、执行说明
├── run.sh         # Bash 测试入口
├── run.py         # Python 测试实现
├── summary.md     # 最近一次测试结果
├── raw.json       # 最近一次机器可读结果
└── logs/          # 历史执行日志
```

前端触发执行的结果必须隔离保存，不允许覆盖上述既有 `summary.md` 和 `raw.json`：

```text
functions/<module>/FN-N/history/
└── web_<timestamp>_<job_id>/
    ├── summary.md
    ├── raw.json
    ├── run.log
    ├── run.json
    ├── stdout.log
    └── metadata.json

functions/history/
└── web_all_<timestamp>_<job_id>/
    ├── summary.md
    ├── raw.json
    ├── run_all.log
    ├── stdout.log
    └── metadata.json
```

说明：

- 原有 `functions/summary.md`、`functions/raw.json` 和各功能点目录下的 `summary.md`、`raw.json` 作为基线/最近一次命令行结果保留。
- 前端点击按钮产生的结果进入 `history/`，不覆盖基线文件。
- 前端默认展示最近一次前端执行结果；如果没有前端执行历史，则展示原有基线结果。
- 页面应明确标注当前结果来源：`前端执行历史` 或 `基线结果`。

重要展示规则：

- 前端所有用户可见模块名称必须使用中文名。
- 前端所有用户可见功能点名称必须使用中文功能名称。
- 前端不展示 `storage`、`rdma`、`mempool` 这类英文目录名。
- 前端不展示 `FN-1`、`FN-2`、`FN-N` 这类内部编号。
- 英文目录名和 `FN-N` 仅允许作为后端 API 参数、文件路径、日志路径或开发调试信息存在。

## 3. 页面信息架构

### 3.1 主页面布局

页面沿用现有 `dashboard/` 的原生 HTML/CSS/JS 风格，不引入构建链。

```text
┌──────────────────────────────────────────────────────────────┐
│ Header：功能验收控制台 / 当前运行状态 / 刷新按钮              │
├───────────────┬──────────────────────────────────────────────┤
│ 左侧模块导航  │ 右侧内容区                                   │
│               │ ┌──────────────────────────────────────────┐ │
│ 多级异构存储  │ │ 顶部功能点跳转窗格                       │ │
│ RDMA分布式    │ └──────────────────────────────────────────┘ │
│ 一致性内存池  │ ┌──────────────────────────────────────────┐ │
│               │ │ 当前功能点详情区                         │ │
│               │ └──────────────────────────────────────────┘ │
└───────────────┴──────────────────────────────────────────────┘
```

### 3.2 左侧三个模块导航窗格

左侧只放三个一级模块，不再混入其他演示入口：

| 前端显示名称 | 内部目录 | 功能点数量 |
|---|---|---:|
| 多级异构的高效能存储模块 | `storage` | 6 |
| RDMA 分布式仿真计算模块 | `rdma` | 5 |
| 一致性总线内存池化仿真计算模块 | `mempool` | 6 |

每个模块导航窗格展示：

- 模块中文名。
- 当前模块统计：`通过 / 失败 / 跳过 / 豁免`。
- 模块整体状态色：
  - 有失败：红色。
  - 有跳过：灰蓝色。
  - 只有通过和豁免：绿色，豁免额外标记。
  - 有 `部分完成`：黄色角标。

点击模块后：

1. 右侧加载该模块。
2. 顶部功能点跳转窗格切换为该模块的中文功能点名称列表。
3. 默认进入该模块第一个功能点；如果模块内存在失败、跳过、豁免或部分完成，优先选中第一个需要关注的功能点。

### 3.3 顶部功能点跳转窗格

进入模块后，右侧顶部显示当前模块下的所有功能点按钮。

示例：

```text
多级异构的高效能存储模块：
[异构存储统一访问接口] [冷热分离与调度] [多策略预取机制] [压缩与去重] [IO 调度与优先级管理] [仿真数据运行中采集]

RDMA 分布式仿真计算模块：
[统一通信层] [聚合数据传输] [流量优先级机制] [CPU 与 GPU 高速直通访问] [路由转发与负载均衡]

一致性总线内存池化仿真计算模块：
[远程内存访问与零拷贝] [分布式内存池 API] [内存池统一命名机制] [自适应分配与热数据迁移] [任务级与用户级内存隔离] [内存池高可靠机制]
```

每个功能点按钮展示：

- 中文功能点名称。
- 最近一次结果状态角标。
- `部分完成` 或 `豁免` 的提示角标。
- 不展示内部编号，例如 `FN-1`。

点击功能点后，详情区切换为该功能点内容。

## 4. 功能点详情区设计

每个功能点详情区固定包含五个窗格。

### 4.1 功能需求说明窗格

用途：说明“这个功能点要求验证什么”。

数据来源：

- 优先读取 `functions/<module>/FN-N/FN-N.md`。
- 同时可从 `raw.json` 补充：
  - `module`
  - `module_name`
  - `fn_id`
  - `function`
  - `source`

展示字段：

- 功能点名称。
- 来源要求。
- 功能点说明。
- 完成判据。
- 测试口径。
- 前置条件。

前端实现建议：

- 如果后端返回解析后的结构化字段，按字段卡片展示。
- 如果只返回 markdown 原文，先以简易 markdown/text 面板展示。
- 需求说明窗格只做解释，不触发执行。
- 对 `FN-N.md` 原文中的内部编号可保留在脚本/原始文档区域；普通说明区应优先展示中文标题和中文描述。

### 4.2 设计与实现说明窗格

用途：说明“我的设计实现在哪里、如何验证”。

数据来源：

- `FN-N.md` 中的“实现位置”“测试方案”“当前验证口径”。
- `raw.json` 中的：
  - `details`
  - `env`
  - `rpc_calls`
  - `completion`
  - `evidence`

展示内容：

- 数据面实现位置。
- 控制面/API/RPC 入口。
- 测试脚本验证路径。
- 当前完成情况：
  - `完成`
  - `部分完成`
  - `未完成`
  - `硬件/环境豁免`
- 对特殊项必须明确说明：
  - CPU 与 GPU 高速直通访问：当前因 GPU Direct 硬件/环境限制标记为豁免。
  - 可配置压缩与去重：压缩已验证，去重当前为代码接入事实。
  - 跨节点内存自适应分配与热数据迁移：当前可观测 TierEngine 迁移闭环。
  - 内存池高可靠机制：默认非破坏性 HA 字段检查。

### 4.3 一键启动测试窗格

用途：通过按钮让后台执行当前功能点测试。

按钮设计：

- 当前功能点详情页提供主按钮：
  - `运行当前功能点测试`
- 可选次按钮：
  - `运行当前模块全部测试`
  - `运行全部功能测试`
- 执行中按钮置灰，显示：
  - `正在执行...`
  - 当前任务编号，使用中文界面标签展示，不直接暴露内部 `job_id`
  - 已运行时间

执行链路：

```text
前端按钮
  -> POST /api/functions/run_one
  -> Flask 校验 module/fn_id/env
  -> 创建 functions/<module>/FN-N/history/web_<timestamp>_<job_id>/
  -> 在临时工作目录或 history 输出目录中执行测试
  -> 将本次 summary/raw/log/stdout 写入 history
  -> 不覆盖 functions/<module>/FN-N/summary.md 和 raw.json
  -> 前端轮询 /api/functions/jobs/<job_id>
  -> job 完成后刷新当前 history 结果
```

运行全部：

```text
POST /api/functions/run_all
  -> 创建 functions/history/web_all_<timestamp>_<job_id>/
  -> 执行全部功能测试
  -> 将本次总 summary/raw/log/stdout 写入 history
  -> 不覆盖 functions/summary.md 和 functions/raw.json
```

运行模块全部：

当前 `functions/` 没有模块级统一入口，建议后端按 catalog 顺序依次执行该模块下所有功能点脚本，并为本次模块执行生成一个 job log。该能力可以作为首版可选项；最低要求是支持单项和 run all。

环境变量配置：

- `CTRL_URL`
- `UDS`
- `REQUIRE_PEER`
- `CURRENT_NODE`
- `ALLOW_DESTRUCTIVE`

默认值：

```text
CTRL_URL=http://127.0.0.1:5000
UDS=/tmp/native_rdma-dp.sock
REQUIRE_PEER=1
ALLOW_DESTRUCTIVE=0
```

安全要求：

- 前端不能传任意 shell 命令。
- 后端只能执行白名单脚本路径。
- 同一时间只允许一个 functions job，避免并发执行争用数据面和日志。
- 前端触发的执行必须写入 `history/`，不能覆盖原有 `summary.md` 和 `raw.json`。
- `ALLOW_DESTRUCTIVE=0` 为默认。
- `mempool/FN-6` 主动 HA 演练必须二次确认，并要求 peer 参数完整。

### 4.4 测试结果展示窗格

用途：展示最近一次测试结果，以及刚刚点击按钮后的执行结果。

数据来源：

- 优先使用 `functions/<module>/FN-N/history/` 下最近一次前端执行结果。
- 如果没有前端执行历史，则使用 `functions/<module>/FN-N/summary.md` 和 `raw.json`。
- 总体结果优先使用 `functions/history/` 下最近一次前端 run all 结果。
- 如果没有前端 run all 历史，则使用 `functions/summary.md` 和 `functions/raw.json`。
- 当前 job 状态 API

展示内容：

- 最近一次运行时间。
- 当前状态：
  - 通过
  - 失败
  - 跳过
  - 豁免
- 完成情况：
  - `完成`
  - `部分完成`
  - `未完成`
  - `硬件/环境豁免`
- 关键证据列表。
- 环境信息。
- RPC 调用摘要。
- 日志路径。
- 如果当前任务正在运行，展示实时输出日志。
- 如果当前任务已完成，自动刷新本次 `history/` 结果，不刷新或覆盖原有基线文件。
- 明确展示结果来源：前端执行历史或基线结果。

状态颜色：

| 状态 | 颜色 | 说明 |
|---|---|---|
| 通过 | 绿色 | 验证通过 |
| 失败 | 红色 | 判据不满足 |
| 跳过 | 灰蓝色 | 前置条件缺失 |
| 豁免 | 紫色/黄色 | 硬件或环境豁免 |

内部数据仍可使用 `PASS`、`FAIL`、`SKIP`、`WAIVED`，但前端普通界面必须映射成中文状态。

### 4.5 测试脚本展示窗格

用途：让用户直接看到当前功能点的测试脚本内容，便于解释“按钮到底执行了什么”。

展示内容：

- `run.sh`
- `run.py`
- 可选：功能点说明文档。
- 可选：最近一次日志尾部内容

交互要求：

- 使用 tab 切换：
  - 启动脚本
  - 测试脚本
  - 结果摘要
  - 原始结果
  - 最新日志
- 代码以只读形式展示。
- 大文件必须走后端 tail 或 size 限制。
- 不提供在线编辑能力。

## 5. 前端目录设计

新增目录：

```text
function_dashboard/
├── index.html
├── styles.css
├── utils.js
├── api.js
├── state.js
├── layout.js
├── module_nav.js
├── fn_nav.js
├── fn_requirement.js
├── fn_implementation.js
├── fn_runner.js
├── fn_result.js
└── fn_script_viewer.js
```

### 5.1 `index.html`

职责：

- 定义 header、左侧模块导航、右侧内容区。
- 加载所有 JS/CSS。
- 初始化默认模块和默认功能点。

### 5.2 `api.js`

职责：

- 封装后端 API：
  - `fetchSummary()`
  - `fetchFunction(module, fnId)`
  - `fetchFile(module, fnId, file)`
  - `fetchLog(module, fnId, name, tailBytes)`
  - `runOne(module, fnId, env)`
  - `runAll(env)`
  - `runModule(module, env)` 可选
  - `fetchJob(jobId)`

### 5.3 `state.js`

职责：

- 保存当前状态：
  - 当前模块。
  - 当前功能点。
  - 总 summary。
  - 当前功能点详情。
  - 当前执行 job。
  - loading/error。

### 5.4 `module_nav.js`

职责：

- 渲染左侧三个模块窗格。
- 点击模块后更新当前模块和功能点列表。

### 5.5 `fn_nav.js`

职责：

- 渲染顶部功能点跳转窗格。
- 按中文功能点名称渲染按钮。
- 点击功能点名称后刷新详情区。
- 内部仍可用 `fn_id` 定位 API，但不得把 `fn_id` 展示给用户。

### 5.6 `fn_requirement.js`

职责：

- 渲染功能需求说明窗格。

### 5.7 `fn_implementation.js`

职责：

- 渲染设计与实现说明窗格。

### 5.8 `fn_runner.js`

职责：

- 渲染一键启动测试窗格。
- 管理运行按钮、环境变量、destructive 确认。
- 创建 job 并轮询执行状态。

### 5.9 `fn_result.js`

职责：

- 渲染测试结果展示窗格。
- job 完成后刷新当前功能点结果。

### 5.10 `fn_script_viewer.js`

职责：

- 渲染测试脚本展示窗格。
- 支持启动脚本、测试脚本、结果摘要、原始结果、最新日志等中文标签页。

## 6. 后端 API 设计

在 `native_rdma/control_plane/app.py` 增加 `function_dashboard` 静态路由和 `/api/functions/*` API。

### 6.1 静态页面路由

新增环境变量：

```text
NR_FUNCTION_DASH_DIR=<repo>/function_dashboard
```

新增路由：

```text
GET /function-dashboard/
GET /function-dashboard/<path>
```

注意：当前 `app.py` 已有 `/<path:p>` catch-all 服务现有 `dashboard/`，因此 `/function-dashboard/*` 必须定义在 catch-all 之前。

### 6.2 `GET /api/functions/summary`

读取：

- 优先读取 `functions/history/` 下最近一次前端 run all 结果。
- 如果不存在前端 run all 历史，再读取 `functions/raw.json` 和 `functions/summary.md`。

返回：

```json
{
  "ok": true,
  "generated_at": "2026-05-03T12:55:42+0800",
  "totals": {
    "total": 17,
    "PASS": 16,
    "FAIL": 0,
    "SKIP": 0,
    "WAIVED": 1
  },
  "modules": {
    "storage": {
      "display_name": "多级异构的高效能存储模块",
      "total": 6,
      "status_counts_text": {"通过": 6, "失败": 0, "跳过": 0, "豁免": 0}
    },
    "rdma": {
      "display_name": "RDMA 分布式仿真计算模块",
      "total": 5,
      "status_counts_text": {"通过": 4, "失败": 0, "跳过": 0, "豁免": 1}
    },
    "mempool": {
      "display_name": "一致性总线内存池化仿真计算模块",
      "total": 6,
      "status_counts_text": {"通过": 6, "失败": 0, "跳过": 0, "豁免": 0}
    }
  },
  "rows": [],
  "summary_md": "...",
  "result_source": "前端执行历史",
  "history_dir": "functions/history/web_all_20260503_153000_xxx"
}
```

说明：

- API 可保留内部状态字段，但必须同时返回中文显示字段。
- 前端展示模块名时使用 `display_name`。
- 前端展示状态统计时使用 `status_counts_text` 或等价中文映射。
- `result_source` 取值建议为 `前端执行历史` 或 `基线结果`。

### 6.3 `GET /api/functions/fn/<module>/<fn_id>`

读取当前功能点的核心文件：

- `FN-N.md`
- 优先读取 `history/` 下最近一次前端执行结果中的 `summary.md` 和 `raw.json`。
- 如果没有前端执行历史，再读取功能点根目录下的 `summary.md` 和 `raw.json`。
- `run.sh`
- `run.py`
- `logs/` 列表

返回：

```json
{
  "ok": true,
  "module": "storage",
  "fn_id": "FN-1",
  "module_display_name": "多级异构的高效能存储模块",
  "function_display_name": "仿真引擎异构存储统一访问接口",
  "status_text": "通过",
  "fn_md": "...",
  "summary_md": "...",
  "raw": {},
  "run_sh": "...",
  "run_py": "...",
  "result_source": "前端执行历史",
  "history_dir": "functions/storage/FN-1/history/web_20260503_153000_xxx",
  "logs": [
    {"name": "run_20260503_125540.log", "size": 12345, "mtime": 1777784140}
  ]
}
```

约束：

- `module` 只能是 `storage`、`rdma`、`mempool`。
- `fn_id` 只能匹配 `FN-[0-9]+`。
- 文件读取必须限制在 `functions/<module>/<fn_id>/` 下。

### 6.4 `GET /api/functions/fn/<module>/<fn_id>/file`

用于脚本展示窗格按需读取文件。

参数：

```text
name=run.py
```

允许文件：

- `FN-N.md`
- `summary.md`
- `raw.json`
- `run.sh`
- `run.py`

返回：

```json
{
  "ok": true,
  "name": "run.py",
  "content": "..."
}
```

### 6.5 `GET /api/functions/fn/<module>/<fn_id>/log`

参数：

```text
name=run_20260503_125540.log
tail_bytes=65536
```

返回：

```json
{
  "ok": true,
  "name": "run_20260503_125540.log",
  "truncated": true,
  "content": "..."
}
```

约束：

- 只允许读取该功能点 `logs/` 目录下文件。
- 默认 tail 64KiB。
- 最大 tail 1MiB。

### 6.6 `POST /api/functions/run_one`

前端点击“运行当前功能点测试”时调用。

请求：

```json
{
  "module": "storage",
  "fn_id": "FN-1",
  "env": {
    "CTRL_URL": "http://127.0.0.1:5000",
    "UDS": "/tmp/native_rdma-dp.sock",
    "REQUIRE_PEER": "1",
    "ALLOW_DESTRUCTIVE": "0",
    "CURRENT_NODE": "A"
  }
}
```

后端执行：

```text
bash functions/<module>/<fn_id>/run.sh
```

执行约束：

- 后端必须为本次前端执行创建独立 history 目录。
- 脚本如果默认会写根目录 `summary.md` 或 `raw.json`，后端必须采用隔离方式避免覆盖：
  - 优先方案：使用脚本支持的 `OUT_DIR`、`LOG_DIR` 环境变量指向本次 history 目录。
  - 兜底方案：执行前复制原始 `summary.md` 和 `raw.json`，执行后将新结果移动到 history，再恢复原始文件。
- 本次 stdout/stderr 写入 history 下的 `stdout.log`。
- job API 返回 `history_dir`。

响应：

```json
{
  "ok": true,
  "job_id": "fn_storage_FN-1_20260503_153000"
}
```

### 6.7 `POST /api/functions/run_all`

前端点击“运行全部功能测试”时调用。

后端执行：

```text
bash functions/run_all.sh
```

执行约束：

- 后端必须为本次前端 run all 创建 `functions/history/web_all_<timestamp>_<job_id>/`。
- 不允许覆盖原有 `functions/summary.md` 和 `functions/raw.json`。
- 如果底层脚本不可避免会覆盖，后端必须执行备份、搬运到 history、恢复原文件的三步保护。
- 本次 stdout/stderr 写入 history 下的 `stdout.log`。

响应：

```json
{
  "ok": true,
  "job_id": "fn_all_20260503_153000"
}
```

### 6.8 `POST /api/functions/run_module`（可选）

前端点击“运行当前模块全部测试”时调用。

由于当前 `functions/` 没有模块级入口，后端可按固定 catalog 顺序执行：

```text
storage: FN-1..FN-6
rdma: FN-1..FN-5
mempool: FN-1..FN-6
```

首版如时间有限，可以不实现 `run_module`，但 UI 上不要展示不可用按钮。

### 6.9 `GET /api/functions/jobs/<job_id>`

前端轮询 job 状态。

返回：

```json
{
  "ok": true,
  "job_id": "fn_storage_FN-1_20260503_153000",
  "kind": "run_one",
  "module": "storage",
  "fn_id": "FN-1",
  "state": "running",
  "exit_code": null,
  "started_at": "...",
  "finished_at": null,
  "stdout_tail": "...",
  "job_log": "functions/storage/FN-1/history/web_20260503_153000_xxx/stdout.log",
  "history_dir": "functions/storage/FN-1/history/web_20260503_153000_xxx"
}
```

状态：

- `queued`
- `running`
- `finished`
- `failed`

## 7. 后端执行安全

必须满足：

1. 不接受任意 shell command。
2. `module` 和 `fn_id` 必须白名单校验。
3. 执行路径必须由后端拼接固定路径。
4. 环境变量只允许白名单键：
   - `CTRL_URL`
   - `UDS`
   - `REQUIRE_PEER`
   - `ALLOW_DESTRUCTIVE`
   - `CURRENT_NODE`
   - `PEER_SSH`
   - `PEER_DP_PATH`
   - `PEER_START_CMD`
5. 同一时间默认只允许一个 functions job。
6. `ALLOW_DESTRUCTIVE=1` 必须后端校验：
   - 只允许指定功能点。
   - 必须携带完整 peer 恢复参数。
   - 前端必须二次确认。
7. 任务标准输出和标准错误写入本次 `history/` 目录下的 `stdout.log`。
8. 前端触发执行不得覆盖原有 `summary.md` 和 `raw.json`。
9. job 完成后不由前端推断结果，前端必须重新读取本次 `history/` 目录下的 `summary.md` 和 `raw.json`。

## 8. 前端中文名称映射

本节中的“前端显示名称”是页面按钮、标题和导航必须使用的名称；内部目录和内部编号只用于 API 与文件定位。

### 8.1 多级异构的高效能存储模块

| 前端显示名称 | 内部定位 |
|---|---|
| 仿真引擎异构存储统一访问接口 | `storage/FN-1` |
| 多层感知、冷热分离与调度 | `storage/FN-2` |
| 多策略预取机制 | `storage/FN-3` |
| 可配置压缩与去重 | `storage/FN-4` |
| IO 调度与优先级管理 | `storage/FN-5` |
| 仿真数据运行中采集 | `storage/FN-6` |

### 8.2 RDMA 分布式仿真计算模块

| 前端显示名称 | 内部定位 |
|---|---|
| RDMA 与 TCP/IP 统一通信层 | `rdma/FN-1` |
| 聚合数据传输 | `rdma/FN-2` |
| 流量优先级机制 | `rdma/FN-3` |
| CPU 与 GPU 高速直通访问 | `rdma/FN-4` |
| 分布式节点路由转发与负载均衡 | `rdma/FN-5` |

### 8.3 一致性总线内存池化仿真计算模块

| 前端显示名称 | 内部定位 |
|---|---|
| RDMA 语义远程内存访问与零拷贝 | `mempool/FN-1` |
| 分布式内存池 API | `mempool/FN-2` |
| 内存池统一命名机制 | `mempool/FN-3` |
| 跨节点内存自适应分配与热数据迁移 | `mempool/FN-4` |
| 任务级与用户级内存隔离 | `mempool/FN-5` |
| 内存池高可靠机制 | `mempool/FN-6` |

## 9. 实施步骤

### 9.1 第一阶段：主流程可用

1. 新增 `function_dashboard/` 静态页面目录。
2. 在 Flask 中增加 `/function-dashboard/` 静态路由。
3. 增加只读 API：
   - `/api/functions/summary`
   - `/api/functions/fn/<module>/<fn_id>`
   - `/api/functions/fn/<module>/<fn_id>/file`
   - `/api/functions/fn/<module>/<fn_id>/log`
4. 增加执行 API：
   - `/api/functions/run_one`
   - `/api/functions/run_all`
   - `/api/functions/jobs/<job_id>`
5. 实现左侧三个模块导航窗格。
6. 实现顶部功能点跳转窗格。
7. 实现五个功能点详情窗格：
   - 功能需求说明。
   - 设计与实现说明。
   - 一键启动测试。
   - 测试结果展示。
   - 测试脚本展示。
8. 验证点击单项测试按钮可以执行后台脚本，并刷新结果。
9. 验证点击 run all 可以执行 `functions/run_all.sh`，并刷新整体状态。
10. 验证前端触发的单项结果写入 `functions/<module>/FN-N/history/`，不覆盖原有 `summary.md` 和 `raw.json`。
11. 验证前端触发的 run all 结果写入 `functions/history/`，不覆盖原有 `functions/summary.md` 和 `functions/raw.json`。
12. 验证前端可见区域只展示中文模块名和中文功能点名，不展示英文目录名或内部编号。

### 9.2 第二阶段：体验增强

1. 增加模块级 run all。
2. 增加 JSON 折叠展示。
3. 增加 markdown 简易渲染。
4. 增加日志搜索和下载。
5. 增加执行历史列表。

## 10. 验收标准

第一阶段完成后必须满足：

- 访问 `/function-dashboard/` 打开新页面。
- 左侧只显示三个模块导航窗格。
- 左侧模块名称只使用中文，不显示 `storage`、`rdma`、`mempool`。
- 点击任意模块后，右侧顶部显示该模块全部功能点跳转按钮。
- 功能点跳转按钮只使用中文功能名称，不显示 `FN-1`、`FN-2` 或类似内部编号。
- 点击任意功能点后，展示该功能点详情。
- 详情区包含五个固定窗格：
  - 功能需求说明。
  - 设计与实现说明。
  - 一键启动测试。
  - 测试结果展示。
  - 测试脚本展示。
- 点击“运行当前功能点测试”后，后台执行对应 `functions/<module>/FN-N/run.sh`。
- 点击“运行全部功能测试”后，后台执行 `functions/run_all.sh`。
- 前端触发的单项测试结果写入该功能点的 `history/` 目录。
- 前端触发的全部测试结果写入 `functions/history/` 目录。
- 前端触发执行不得覆盖原有 `summary.md` 和 `raw.json`。
- 执行过程中可以看到任务状态和实时输出日志。
- 执行完成后自动刷新当前功能点的 history 结果。
- 前端展示的状态与当前结果来源一致；如果有前端执行历史，以 history 结果为准，否则以基线 `summary.md`、`raw.json` 为准。
- 启动脚本和测试脚本可以在测试脚本窗格中只读查看，标签使用中文。
- 不影响现有 `/` 下的 `dashboard/`。
- 默认不能触发 destructive HA 演练。

## 11. 后续注意事项

1. 现有 `functions/raw.json` 包含绝对路径，API 应额外返回 repo-relative path，前端优先展示相对路径。
2. 日志文件可能较大，日志读取必须 tail，不能整文件无限制返回。
3. 前端不直接解析脚本退出码作为验收结果，最终结果以当前结果来源中的 `summary.md` 和 `raw.json` 为准。
4. `run_module` 可选；如果不实现，不要在 UI 上展示“运行当前模块全部测试”按钮。
5. 后续如需把 `function_dashboard/` 设为默认首页，需要单独确认，不在本方案首版范围内。
