#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""功能 2.2 — 聚合数据传输。

验证聚合写入功能：100 个与 1000 个 1KB 对象能够在一个 aio 批次内
完成提交和等待。

方法
----
利用 `librados` 的 `aio_write_full` 把一批对象并发提交到一个 IOContext，
最后 `wait_for_complete`——librados 内部会将同 PG 的 IO 聚合上线。

执行
----
    python3 test_02_batch_aggregation.py
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "common"))
from ceph_helper import assert_le, ok, rados_pool  # noqa: E402

POOL = "test_batch_pool"
OBJ_SIZE = 1024


def run_case(ioctx, batch, per_batch, tag):
    payload = os.urandom(OBJ_SIZE)
    start = time.perf_counter()
    for b in range(batch):
        comps = []
        for j in range(per_batch):
            comp = ioctx.aio_write_full(f"{tag}_b{b}_{j}", payload)
            comps.append(comp)
        for c in comps:
            c.wait_for_complete()
    return (time.perf_counter() - start) * 1000  # ms


def main():
    with rados_pool(POOL) as (_, ioctx):
        t1 = run_case(ioctx, batch=1, per_batch=100, tag="A")
        t2 = run_case(ioctx, batch=1, per_batch=1000, tag="B")
    assert_le(t1, 100, "single 100-object batch", " ms")
    assert_le(t2, 200, "single 1000-object batch", " ms")
    ok("functional 2.2 PASS — batch aggregation")


if __name__ == "__main__":
    main()
