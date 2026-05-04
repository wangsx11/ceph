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
