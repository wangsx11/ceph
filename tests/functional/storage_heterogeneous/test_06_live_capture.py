#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""功能 1.6 — 仿真数据运行中采集。

目的
----
验证在持续写入仿真对象时（producer），并发读线程（consumer）能实时
读取到最新状态，不被写者长时间阻塞。

断言
----
- 1000 次读操作的中位延迟 ≤ 500μs；
- 无读失败；
- 消费者观察到的 version 单调递增。

执行
----
    python3 test_06_live_capture.py
"""
import os
import sys
import threading
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "common"))
from ceph_helper import assert_le, die, info, ok, rados_pool  # noqa: E402

POOL = "test_live_pool"
OBJ = "live_entity_0001"


def main():
    stop = threading.Event()
    versions = []

    def producer():
        with rados_pool(POOL) as (_, ioctx):
            v = 0
            while not stop.is_set():
                v += 1
                ioctx.write_full(OBJ, str(v).encode())
                ioctx.set_xattr(OBJ, "version", str(v).encode())

    t = threading.Thread(target=producer, daemon=True)
    t.start()
    time.sleep(0.5)

    latencies = []
    with rados_pool(POOL) as (_, ioctx):
        for _ in range(1000):
            s = time.perf_counter()
            try:
                data = ioctx.read(OBJ)
            except Exception:
                die("live read failed")
            latencies.append((time.perf_counter() - s) * 1e6)
            try:
                versions.append(int(data.decode()))
            except Exception:
                pass
    stop.set(); t.join(1)

    latencies.sort()
    p50 = latencies[len(latencies) // 2]
    info(f"read-while-write latency P50 = {p50:.1f} μs  samples={len(latencies)}")
    assert_le(p50, 500, "live-capture P50", " μs")

    # monotonic check (allow duplicates since same value can be read twice)
    last = 0
    for v in versions:
        if v < last:
            die(f"version went backwards: {last} -> {v}")
        last = v
    ok("functional 1.6 PASS — live simulation data capture")


if __name__ == "__main__":
    main()
