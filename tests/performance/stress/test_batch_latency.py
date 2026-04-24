#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""性能指标 4 — 批处理耗时。

1000 批 × 100 obj × 1KB ≤ 200 ms；
100 批 × 1000 obj × 1KB ≤ 100 ms。
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "common"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ceph_helper import rados_pool  # noqa: E402
from _report import record  # noqa: E402

POOL = "perf_batch_pool"
SIZE = 1024


def run_case(ioctx, batch, per_batch, tag):
    payload = os.urandom(SIZE)
    start = time.perf_counter()
    for b in range(batch):
        comps = [ioctx.aio_write_full(f"{tag}_{b}_{j}", payload) for j in range(per_batch)]
        for c in comps:
            c.wait_for_complete()
    return (time.perf_counter() - start) * 1000.0


def main():
    with rados_pool(POOL) as (_, ioctx):
        t1 = run_case(ioctx, 1000, 100, "A")
        t2 = run_case(ioctx,  100, 1000, "B")
    record("batch_1000x100_ms", t1, target=200.0, unit=" ms", passed=t1 <= 200)
    record("batch_100x1000_ms", t2, target=100.0, unit=" ms", passed=t2 <= 100)


if __name__ == "__main__":
    main()
