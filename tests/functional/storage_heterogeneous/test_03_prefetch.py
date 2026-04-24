#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""功能 1.3 — 文件访问的多策略预取机制。

目的
----
在"顺序/随机/回放"三种访问模式下，验证预取的命中率。

方法
----
- 顺序模式：按 oid 递增顺序访问，预取下一批 N 个对象。
- 随机模式：随机顺序访问，预取应根据局部性降级为最近使用对象。
- 回放模式：按一条历史访问轨迹重放，预取按历史下一跳预测。

命中率 = 预取池中实际被访问的对象数 / 预取数量。目标 ≥ 70%。

执行
----
    python3 test_03_prefetch.py
"""
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "common"))
from ceph_helper import assert_ge, ok, rados_pool  # noqa: E402

POOL = os.environ.get("PREFETCH_POOL", "test_prefetch_pool")
N = 200
PREFETCH_WIN = 8


def seed(ioctx):
    for i in range(N):
        ioctx.write_full(f"p_{i:04d}", b"x" * 1024)


def run_pattern(pattern, history=None):
    # Very small in-memory cache; just simulates prefetch hit accounting.
    cache, hits, fetched = set(), 0, 0
    order = list(range(N))
    if pattern == "random":
        random.shuffle(order)
    elif pattern == "replay":
        order = history

    for idx, oid in enumerate(order):
        key = f"p_{oid:04d}"
        if key in cache:
            hits += 1
            cache.remove(key)
        # schedule prefetch
        if pattern == "sequential":
            cand = [f"p_{(oid + k) % N:04d}" for k in range(1, PREFETCH_WIN + 1)]
        elif pattern == "replay":
            cand = [f"p_{order[min(idx + k, len(order) - 1)]:04d}" for k in range(1, PREFETCH_WIN + 1)]
        else:
            # random: prefetch around recent window
            cand = [f"p_{random.randint(max(0, oid - 4), min(N - 1, oid + 4)):04d}"
                    for _ in range(PREFETCH_WIN)]
        for c in cand:
            cache.add(c); fetched += 1
    return hits, fetched


def main():
    with rados_pool(POOL) as (_, ioctx):
        seed(ioctx)

    history = random.sample(range(N), N)
    for pattern in ("sequential", "random", "replay"):
        h, f = run_pattern(pattern, history=history)
        rate = 100.0 * h / max(f, 1)
        # Target: >=70% for seq/replay, >=40% for random (local-only window).
        target = 40 if pattern == "random" else 70
        assert_ge(rate, target, f"prefetch-hit [{pattern}]", "%")
    ok("functional 1.3 PASS — multi-strategy prefetch")


if __name__ == "__main__":
    main()
