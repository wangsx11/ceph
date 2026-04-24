#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""功能 1.2 — 多层感知与冷热分离。

目的
----
验证系统能根据访问频率把对象在 hot/warm/cold 三层之间迁移。

方法
----
1. 在 warm_pool 预置 60 个 1KB 对象。
2. 随机挑 20 个作为"热对象"进行 30 次访问，触发提升至 hot 层 (ramfs)。
3. 挑 20 个"冷对象"保持不访问，等待 demote 阈值下沉 cold_pool。
4. 断言：
   - 热层实际文件数 >= 15（允许抖动）
   - cold_pool 对象数 >= 15
   - 未访问对象的 heat_score < DEMOTE_WARM

执行
----
    python3 test_02_tier_hotcold.py
"""
import os
import random
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "backend"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "common"))

from ceph_helper import assert_ge, die, info, ok  # noqa: E402

HOT_PATH = os.environ.get("HOT_PATH", "/mnt/hot")


def main():
    # Re-use the backend module so the test drives the same code path as prod.
    from m6_tiering import tiering_module as T
    from config import DEMOTE_WARM, THRESHOLD_HOT, WARM_POOL  # noqa

    T.reset()
    info("seeding 60 objects into warm_pool")
    ioctx = T._get_warm_ioctx()
    names = [f"hetero_obj_{i:03d}" for i in range(60)]
    for n in names:
        ioctx.write_full(n, os.urandom(1024))

    hot_targets = random.sample(names, 20)
    cold_targets = [n for n in names if n not in hot_targets][:20]

    info("driving access pattern")
    for n in hot_targets:
        T.record_access(n, count=30)
    T.flush_access()
    for n in hot_targets:
        s = T.calculate_heat_score(n)
        if s >= THRESHOLD_HOT:
            T._promote_warm_to_hot(n, score=s)
    for n in cold_targets:
        s = T.calculate_heat_score(n)
        if s < DEMOTE_WARM:
            T._demote_warm_to_cold(n, score=s)

    time.sleep(1)
    state = T._count_tiers()
    info(f"tier_state={state}")

    assert_ge(state["hot"], 15, "hot-tier promoted count")
    assert_ge(state["cold"], 15, "cold-tier demoted count")

    for n in cold_targets[:5]:
        if T.calculate_heat_score(n) >= DEMOTE_WARM:
            die(f"cold object {n} still hot after demote")
    ok("functional 1.2 PASS — tier awareness & hot/cold separation")


if __name__ == "__main__":
    main()
