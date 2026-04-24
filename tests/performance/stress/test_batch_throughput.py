#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""性能指标 5 — 批处理吞吐 ≥ 700 MB/s。"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "common"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from ceph_helper import rados_pool  # noqa: E402
from _report import record  # noqa: E402

POOL = "perf_batch_tp"
SIZE = 1024
TOTAL_OBJS = 200_000


def main():
    payload = os.urandom(SIZE)
    with rados_pool(POOL) as (_, ioctx):
        start = time.perf_counter()
        batch = 0; comps = []
        while batch < TOTAL_OBJS:
            for _ in range(1000):
                comps.append(ioctx.aio_write_full(f"bt_{batch:07d}", payload))
                batch += 1
            for c in comps:
                c.wait_for_complete()
            comps.clear()
        dur = time.perf_counter() - start
    total_mb = TOTAL_OBJS * SIZE / 1_048_576
    tp = total_mb / dur
    record("batch_throughput_mbps", tp, target=700.0, unit=" MB/s", passed=tp >= 700)


if __name__ == "__main__":
    main()
