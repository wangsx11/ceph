#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""性能指标 2 — 10 万对象 1KB 端到端时延。

目标：平均 ≤ 50μs，P99 ≤ 100μs。
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "common"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from ceph_helper import rados_pool  # noqa: E402
from _report import record  # noqa: E402

POOL = "perf_latency_pool"
N = 100_000
SIZE = 1024


def main():
    payload = os.urandom(SIZE)
    lats = []
    with rados_pool(POOL) as (_, ioctx):
        # prefill so we test steady-state write overwrite latency
        for i in range(N):
            t0 = time.perf_counter_ns()
            ioctx.write_full(f"lat_{i:06d}", payload)
            lats.append((time.perf_counter_ns() - t0) / 1000.0)

    lats.sort()
    avg = sum(lats) / len(lats)
    p99 = lats[int(len(lats) * 0.99)]
    record("e2e_latency_avg_us", avg, target=50,  unit="μs", passed=avg <= 50)
    record("e2e_latency_p99_us", p99, target=100, unit="μs", passed=p99 <= 100)


if __name__ == "__main__":
    main()
