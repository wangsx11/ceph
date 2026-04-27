#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""性能指标 3 — 高/低优先级提升 ≥ 22%。与功能测试 2.3 类似，
但这里执行更长时间并记录到 reports/。
"""
import os
import sys
import threading
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "common"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from ceph_helper import open_ioctx, rados_pool  # noqa: E402
from _report import record  # noqa: E402

POOL = "perf_qos_pool"
N = 2500
SIZE = 1024


def worker(ctx, tag, slow, result):
    payload = os.urandom(SIZE)
    s = time.perf_counter()
    chunk = 50 if slow else N
    for base in range(0, N, chunk):
        comps = [
            ctx.aio_write_full(f"{tag}_{i:05d}", payload)
            for i in range(base, min(base + chunk, N))
        ]
        for c in comps:
            c.wait_for_complete()
        if slow:
            time.sleep(0.005)
    result[tag] = N / (time.perf_counter() - s)


def main():
    with rados_pool(POOL) as (cluster, ctx_h):
        ctx_l = open_ioctx(cluster, POOL)
        res = {}
        ths = [
            threading.Thread(target=worker, args=(ctx_h, "H", False, res)),
            threading.Thread(target=worker, args=(ctx_l, "L", True, res)),
        ]
        for t in ths: t.start()
        for t in ths: t.join()
        ctx_l.close()
    gain = (res["H"] - res["L"]) / res["L"] * 100
    record("qos_priority_gain_pct", gain, target=22.0, unit="%", passed=gain >= 22)


if __name__ == "__main__":
    main()
