#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""性能指标 9 — 仿真引擎内存池化开销。

对比 `malloc/free` 与 `rdma_mempool.alloc/free`：
- 性能损失 ≤ 5%
- 高并发吞吐提升 ≥ 20%
"""
import os
import sys
import threading
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "backend_v2"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "common"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from _report import record  # noqa: E402

N = 200_000
SIZE = 1024
THREADS = 16


def raw_alloc():
    start = time.perf_counter()
    for _ in range(N):
        _ = bytearray(SIZE)
    return N / (time.perf_counter() - start)


def pool_alloc():
    from rdma_mempool import MemPool
    mp = MemPool("bench_single", size_mb=512)
    start = time.perf_counter()
    for _ in range(N):
        h = mp.alloc(SIZE)
        mp.free(h)
    tp = N / (time.perf_counter() - start)
    return tp


def pool_alloc_parallel():
    from rdma_mempool import MemPool
    mp = MemPool("bench_mt", size_mb=2048)
    stop = [False]; counter = [0]

    def worker():
        local = 0
        while not stop[0]:
            h = mp.alloc(SIZE); mp.free(h); local += 1
        counter[0] += local

    ths = [threading.Thread(target=worker) for _ in range(THREADS)]
    for t in ths: t.start()
    time.sleep(5)
    stop[0] = True
    for t in ths: t.join()
    return counter[0] / 5.0


def raw_alloc_parallel():
    stop = [False]; counter = [0]

    def worker():
        local = 0
        while not stop[0]:
            _ = bytearray(SIZE); local += 1
        counter[0] += local

    ths = [threading.Thread(target=worker) for _ in range(THREADS)]
    for t in ths: t.start()
    time.sleep(5)
    stop[0] = True
    for t in ths: t.join()
    return counter[0] / 5.0


def main():
    raw = raw_alloc()
    pool = pool_alloc()
    overhead = (raw - pool) / raw * 100 if pool < raw else 0.0
    record("mempool_single_overhead_pct", overhead, target=5.0, unit="%",
           passed=overhead <= 5.0)

    raw_mt = raw_alloc_parallel()
    pool_mt = pool_alloc_parallel()
    gain = (pool_mt - raw_mt) / raw_mt * 100
    record("mempool_mt_gain_pct", gain, target=20.0, unit="%",
           passed=gain >= 20.0)


if __name__ == "__main__":
    main()
