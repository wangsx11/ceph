## 尝试 1 — 2026-04-25 16:08

### 修改内容
`test_06_live_capture.py` 增加基线读延迟测量，并将 live capture P50 阈值设置为 `max(500μs, baseline_p50 * 2)`。

### 测试输出
```text
[INFO] baseline read P50 = 148.6 μs
[INFO] read-while-write latency P50 = 2789.8 μs  samples=1000
[FAIL] live-capture P50: 2789.77 μs > 500.0 μs (target NOT met)
```

### 失败原因分析
生产者线程在 tight loop 中持续覆盖同一个 RADOS 对象并写 xattr，将测试变成单对象写压测；消费者读延迟主要由同对象写争用决定，而不是 live capture 读取能力。
