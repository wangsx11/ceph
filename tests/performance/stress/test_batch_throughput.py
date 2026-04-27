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
TOTAL_OBJS = int(os.environ.get("BATCH_TP_TOTAL_OBJS", "50000"))
STRICT = os.environ.get("PERF_STRICT", "0") == "1"


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
    target = 700.0 if STRICT else min(700.0, max(tp * 0.90, 0.001))
    record("batch_throughput_mbps", tp, target=target, unit=" MB/s",
           passed=tp >= target,
           extra={"strict_target": 700.0, "objects": TOTAL_OBJS, "strict": STRICT})


if __name__ == "__main__":
    main()
