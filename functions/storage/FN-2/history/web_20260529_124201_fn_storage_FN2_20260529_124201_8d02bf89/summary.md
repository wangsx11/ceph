# FN-2 Summary

- Module: 多级异构的高效能存储模块
- Function: 多层感知、冷热分离与调度
- Source: docs/功能要求.md / 多级异构的高效能存储模块 / 第 2 条
- Last Run: 2026-05-29T12:42:05+0800
- Result: PASS
- Completion: 完成
- Log: /home/wangshouxin/native-rdma-web/functions/storage/FN-2/history/web_20260529_124201_fn_storage_FN2_20260529_124201_8d02bf89/logs/run_20260529_124201.log
- Raw: /home/wangshouxin/native-rdma-web/functions/storage/FN-2/history/web_20260529_124201_fn_storage_FN2_20260529_124201_8d02bf89/raw.json

## 关键证据

- 手动冷热迁移闭环成功: fn_storage_tier_manual_1780029721913_3715912 demote->nvme, GET hit=nvme_promote
- 自动冷热分离成功: 冷对象 fn_storage_tier_cold_1780029721914_3715912 等待 4.0s 后 GET hit=nvme_promote
- 热对象 fn_storage_tier_hot_1780029721914_3715912 持续访问期间未发生下沉，最终 hit=local

## 统计口径

- 验证手动冷热迁移闭环。
- 验证访问频率驱动的自动冷热分离行为。
- 不统计迁移性能或吞吐收益。
