# FN-2 Summary

- Module: 多级异构的高效能存储模块
- Function: 多层感知、冷热分离与调度
- Source: docs/功能要求.md / 多级异构的高效能存储模块 / 第 2 条
- Last Run: 2026-05-04T11:21:46+0800
- Result: PASS
- Completion: 完成
- Log: /home/wangshouxin/native-rdma-web/functions/storage/FN-2/logs/run_20260504_112142.log
- Raw: /home/wangshouxin/native-rdma-web/functions/storage/FN-2/raw.json

## 关键证据

- 手动冷热迁移闭环成功: fn_storage_tier_manual_1777864902811_60186 demote->nvme, GET hit=nvme_promote
- 自动冷热分离成功: 冷对象 fn_storage_tier_cold_1777864902812_60186 等待 16.0s 后 GET hit=nvme_promote
- 热对象 fn_storage_tier_hot_1777864902812_60186 持续访问期间未发生下沉，最终 hit=local

## 统计口径

- 验证手动冷热迁移闭环。
- 验证访问频率驱动的自动冷热分离行为。
- 不统计迁移性能或吞吐收益。
