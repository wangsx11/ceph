---
name: native-rdma-project-onboarding
description: 在 native_rdma 项目的新会话开始时使用本 skill，用于快速了解 native_rdma 开发模块、function_dashboard / performance_dashboard / dashboard 三类前端的职责、顶层目录分工、关键文档、启动入口和修改前优先阅读的文件。
---

# native_rdma 项目上下文

新的 AI 会话先读本文件，再按任务类型去读对应模块。

## 一句话

`native_rdma/` 是项目的开发模块和热路径实现；`function_dashboard/` 是功能验收前端；`performance_dashboard/` 是性能验收前端；`dashboard/` 是演示内容前端。真实执行逻辑在 `native_rdma/`、`functions/`、`performances/`，前端主要负责展示、触发和结果浏览。

## 先读什么

1. 先读本 `SKILL.md`。
2. 再按任务类型读这些文档：
   - 项目总览：`docs/自研方案.md`
   - 功能要求：`docs/功能要求.md`
   - 性能要求：`docs/性能要求.md`
   - 演示要求：`docs/演示要求.md`
   - 功能目录设计：`docs/功能指标拆分与functions目录需求.md`
   - 性能目录设计：`docs/性能指标拆分与performances目录需求.md`
   - 功能前端文案与证据：`docs/function_dashboard验证与实现文案.md`
   - 性能前端文案与证据：`docs/performance_dashboard验证与实现文案.md`
   - 硬件与部署约束：`docs/硬件配置.md`
   - 当前完成度/证据：`docs/functions实现完成度.md`、`docs/功能要求实现完整性检查.md`、`docs/性能原始结果解读.md`
3. 如果要改代码，先找到对应顶层模块，再动手：
   - `native_rdma/`
   - `function_dashboard/`
   - `performance_dashboard/`
   - `dashboard/`
   - `functions/`
   - `performances/`

## 顶层目录分工

- `native_rdma/`：主开发模块。`data_plane/` 是 C++ 数据面热路径，`control_plane/` 是 Flask 控制面和 UDS/API，`proto/` 是协议定义，`deploy/` 是节点配置，`scripts/` 是启动/停止/健康检查/验收脚本，`tests/` 是旧的功能与性能验证辅助代码。
- `function_dashboard/`：功能验收控制台。页面路径是 `/function-dashboard/`，对应 API 是 `/api/functions/*`。它只负责展示功能要求、实现证据、运行结果和脚本，不负责核心验收逻辑。它是静态 HTML/CSS/JS，不需要单独前端开发服务器。
- `performance_dashboard/`：性能验收控制台。页面路径是 `/performance-dashboard/`，对应 API 是 `/api/performance/*`。它只负责展示性能要求、结果摘要和原始结果，不负责压测逻辑。它也是静态 HTML/CSS/JS。
- `dashboard/`：演示内容前端。页面路径是 `/`，以 `dashboard/index.html` 实际加载的 JS 为准；目录中包含 demo 3 / 5 / 6 以及路由、隔离、HA、仿真采集等演示脚本。
- `functions/`：功能验收结果与执行入口。重点看 `run_all.sh`、`run_all.py`、`summary.md`、`raw.json`，以及各 `functions/<module>/FN-N/` 子目录和 `history/`。
- `performances/`：性能验收结果与执行入口。重点看 `run_all.sh`、`run_all.py`、`summary.md`，以及各 `performances/PF-N/` 子目录和 `history/`。

## 关键入口

- Flask 控制面统一在 `native_rdma/control_plane/app.py`，它同时服务：
  - `/`
  - `/function-dashboard/`
  - `/performance-dashboard/`
  - `/api/demo3/*`、`/api/demo5/*`、`/api/demo6/*`
  - `/api/route/*`、`/api/iso/*`、`/api/ha/*`、`/api/sim/*`
  - `/api/functions/*`
  - `/api/performance/*`
- 推荐的整套启动入口仍然是 `cd native_rdma && bash start.sh`，以脚本当前实现为准。
- 功能总跑入口：`bash functions/run_all.sh`
- 性能总跑入口：`bash performances/run_all.sh`

## 修改前先看

- 改启动、同步、节点拉起流程前，先看 `native_rdma/start.sh`、`native_rdma/scripts/demo_up.sh`、`native_rdma/scripts/start_node.sh`、`native_rdma/deploy/node_a.env`、`native_rdma/deploy/node_b.env`。
- 改控制面 API 前，先看 `native_rdma/control_plane/app.py`，必要时再追到 `native_rdma/data_plane/main.cpp` 和对应 C++ 模块。
- 改功能前端前，先看 `function_dashboard/index.html` 和对应 `function_dashboard/*.js`，并确认它们消费的是 `/api/functions/*`。
- 改性能前端前，先看 `performance_dashboard/index.html` 和对应 `performance_dashboard/*.js`，并确认它们消费的是 `/api/performance/*`。
- 改演示前端前，优先看仓库根 `dashboard/index.html` 和对应 demo JS；`native_rdma/dashboard/` 是旧单页页面，通常只在维护历史代码时参考。
- 不要删除或回退工作区里不属于你的改动。

## 常用验证

- C++ 改动：

```bash
cd native_rdma
cmake --build build -j
```

- Python 控制面语法检查：

```bash
python3 -m py_compile native_rdma/control_plane/*.py
```

- 功能验收总跑：

```bash
bash functions/run_all.sh
```

- 性能验收总跑：

```bash
bash performances/run_all.sh
```
