#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""功能 3.4 — 本地/远端自适应分配 + 热数据迁移。

- MemPool.alloc(..., hint="hot") → 尝试本地 DRAM 分配；
- 冷对象分配到远端 region；
- 迁移计数器应随 `record_access` 增加而触发，将冷对象从远端复制回本地。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "backend_v2"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "common"))

from ceph_helper import assert_ge, info, ok  # noqa: E402


def main():
    from rdma_mempool import MemPool

    mp = MemPool("test_adaptive", size_mb=32, local_quota_mb=8)
    handles_hot = [mp.alloc(1024, hint="hot") for _ in range(50)]
    handles_cold = [mp.alloc(1024, hint="cold") for _ in range(200)]

    stats = mp.stats()
    info(f"initial placement: {stats}")
    assert_ge(stats["local"], 50, "hot hint local count")
    assert_ge(stats["remote"], 150, "cold hint remote count")

    # heat some cold ones
    for h in handles_cold[:30]:
        for _ in range(20):
            mp.read(h)
    mp.rebalance()
    stats2 = mp.stats()
    info(f"after rebalance: {stats2}")
    assert_ge(stats2["migrations"], 10, "migrations triggered")

    for h in handles_hot + handles_cold:
        mp.free(h)
    ok("functional 3.4 PASS — adaptive local/remote allocation")


if __name__ == "__main__":
    main()
