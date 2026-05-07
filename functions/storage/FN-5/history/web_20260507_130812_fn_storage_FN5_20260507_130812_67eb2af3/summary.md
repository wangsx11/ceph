# FN-5 Summary

- Module: 多级异构的高效能存储模块
- Function: IO 调度与优先级管理
- Source: docs/功能要求.md / 多级异构的高效能存储模块 / 第 5 条
- Last Run: 2026-05-07T13:08:12+0800
- Result: PASS
- Completion: 完成
- Log: /home/wangshouxin/native-rdma-web/functions/storage/FN-5/history/web_20260507_130812_fn_storage_FN5_20260507_130812_67eb2af3/logs/run_20260507_130812.log
- Raw: /home/wangshouxin/native-rdma-web/functions/storage/FN-5/history/web_20260507_130812_fn_storage_FN5_20260507_130812_67eb2af3/raw.json

## 关键证据

- 数据面日志包含 IoScheduler 前台/后台队列初始化: /home/wangshouxin/native-rdma-web/native_rdma/logs/dp_A.log
- 前台 NVMe I/O 计数增加: fg_write_ops +1, fg_read_ops +1
- 后台 HDD I/O 计数增加: bg_write_ops +1, bg_read_ops +1

## 统计口径

- 验证前台/后台队列初始化。
- 验证前台/后台 I/O 路径真实可观测。
- 不统计优先级吞吐提升比例。
