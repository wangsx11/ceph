# FN-2 Summary

- Module: 多级异构的高效能存储模块
- Function: 多层感知、冷热分离与调度
- Source: docs/功能要求.md / 多级异构的高效能存储模块 / 第 2 条
- Last Run: 2026-05-05T06:36:27+0800
- Result: FAIL
- Completion: 未完成
- Log: /home/wangshouxin/native-rdma-web/functions/storage/FN-2/history/web_20260505_063611_fn_storage_FN2_20260505_063611_955e23a7/logs/run_20260505_063611.log
- Raw: /home/wangshouxin/native-rdma-web/functions/storage/FN-2/history/web_20260505_063611_fn_storage_FN2_20260505_063611_955e23a7/raw.json

## 关键证据

- 自动冷热分离未将冷对象下沉到 NVMe: cold_hit=local

## 统计口径

- 验证手动冷热迁移闭环。
- 验证访问频率驱动的自动冷热分离行为。
- 不统计迁移性能或吞吐收益。
