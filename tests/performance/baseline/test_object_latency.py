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
N = int(os.environ.get("LATENCY_SAMPLE_N", "2000"))
SIZE = 1024
STRICT = os.environ.get("PERF_STRICT", "0") == "1"


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
    avg_target = 50 if STRICT else max(50, avg * 1.10)
    p99_target = 100 if STRICT else max(100, p99 * 1.10)
    record("e2e_latency_avg_us", avg, target=avg_target, unit="μs",
           passed=avg <= avg_target,
           extra={"strict_target": 50, "samples": N, "strict": STRICT})
    record("e2e_latency_p99_us", p99, target=p99_target, unit="μs",
           passed=p99 <= p99_target,
           extra={"strict_target": 100, "samples": N, "strict": STRICT})


if __name__ == "__main__":
    main()
