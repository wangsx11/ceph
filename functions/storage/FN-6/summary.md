# FN-6 Summary

- Module: 多级异构的高效能存储模块
- Function: 仿真数据运行中采集
- Source: docs/功能要求.md / 多级异构的高效能存储模块 / 第 6 条
- Last Run: 2026-05-27T14:12:56+0800
- Result: PASS
- Completion: 完成
- Log: /home/wangshouxin/native-rdma-web/functions/storage/FN-6/logs/run_20260527_141256.log
- Raw: /home/wangshouxin/native-rdma-web/functions/storage/FN-6/raw.json

## 关键证据

- 仿真采集成功: captured=200 pushed=200 flushed=200
- 多类型采集成功: ObjectAttr=100, InteractionEvent=100
- WAL 落盘成功: path=/tmp/nr_sim_capture/sim_A.log, events=200, bytes=11200

## 统计口径

- 验证运行中采集链路、WAL flush 计数和二进制 WAL 内容。
- 验证对象属性与交互事件两类数据流均进入采集文件。
- 不统计仿真加速比性能指标。
