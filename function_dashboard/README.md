# 功能验收控制台启动说明

`function_dashboard/` 是由 Flask 控制面静态托管的原生 HTML/CSS/JS 前端，不需要单独安装 npm 依赖，也不需要启动独立前端开发服务器。

## 完整启动

在节点 A 上启动完整 native_rdma 演示环境：

```bash
cd /home/wangshouxin/ceph-web/native_rdma
bash start.sh
```

启动后访问：

```text
http://192.168.0.218:5000/function-dashboard/
```

原有 dashboard 仍然在：

```text
http://192.168.0.218:5000/
```

## 仅启动 Flask 控制面

如果只需要查看页面和调试 `/api/functions/*`，可以只启动 Flask 后端：

```bash
cd /home/wangshouxin/ceph-web
PYTHONPATH=native_rdma/control_plane python3 native_rdma/control_plane/app.py
```

然后访问：

```text
http://127.0.0.1:5000/function-dashboard/
```

这种方式不会自动拉起数据面；依赖 UDS 或 peer 的功能验收脚本可能返回跳过或环境不可用。

## 执行结果目录

从页面触发的单项功能测试会写入：

```text
functions/<module>/FN-N/history/web_<timestamp>_<job_id>/
```

从页面触发的全部功能测试会写入：

```text
functions/history/web_all_<timestamp>_<job_id>/
```

前端触发执行会保护原有 `summary.md` 和 `raw.json`，不会覆盖命令行基线结果。
