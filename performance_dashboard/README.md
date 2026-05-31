# 性能验收控制台启动说明

`performance_dashboard/` 是由 Flask 控制面静态托管的原生 HTML/CSS/JS 前端，布局和交互参照 `function_dashboard/`，不需要单独安装 npm 依赖。

## 完整启动

在节点 A 上启动完整 native_rdma 演示环境：

```bash
cd /home/wangshouxin/native-rdma-web/native_rdma
bash start.sh
```

启动后访问：

```text
http://192.168.0.218:5000/performance-dashboard/
```

功能验收控制台仍然在：

```text
http://192.168.0.218:5000/function-dashboard/
```

## 仅启动 Flask 控制面

如果只需要查看页面和调试 `/api/performance/*`：

```bash
cd /home/wangshouxin/native-rdma-web
PYTHONPATH=native_rdma/control_plane python3 native_rdma/control_plane/app.py
```

然后访问：

```text
http://127.0.0.1:5000/performance-dashboard/
```

这种方式不会自动拉起数据面；依赖 UDS、RDMA peer、fio 或特定硬件环境的性能测试可能失败。

## 执行结果目录

从页面触发的单项性能测试会写入：

```text
performances/PF-N/history/web_<timestamp>_<job_id>/
```

从页面触发的全部性能测试会写入：

```text
performances/history/web_all_<timestamp>_<job_id>/
performances/PF-N/history/web_all_<timestamp>_<job_id>/
```

前端触发执行会保护原有 `summary.md` 和 `raw.json`，不会覆盖命令行基线结果。

## 运行模式

性能控制台默认使用演示安全模式。点击“运行演示性能流”时，后端会创建一次新的 web_all 历史目录，并把现有 PF 证据复制到该目录展示，不从浏览器按钮启动长时间高压性能套件。这样可以避免 PF-1、PF-6 等高负载项在现场造成长时间等待或网络风险。

完整验收路径不变，仍然使用：

```bash
cd /home/wangshouxin/native-rdma-web
bash performances/run_all.sh
```

演示安全模式生成的 `summary.md` / `raw.json` 会标记 profile 为 `presentation`，只能作为演示流证据索引，不能替代完整验收。

PF-7 备份延迟项有两层状态：`passed=true` 表示自动化 4KB 写入 P999 延迟子项通过；
严格 3+1 RAID5 验收还必须看到 `strict_acceptance_passed=true`。如果只看到
`raid5_confirmed=false`，页面可以展示延迟证据，但最终验收仍需补充 RAID5 拓扑确认。
