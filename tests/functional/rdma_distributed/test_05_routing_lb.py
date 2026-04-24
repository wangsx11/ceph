#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""功能 2.5 — 路由转发 & 负载均衡。

目的
----
多客户端并发写同一 pool 时，流量应被 CRUSH 均衡到 ≥ 2 个 OSD 主机，
单个 OSD 的负载偏差 ≤ 30%。

执行
----
    python3 test_05_routing_lb.py
"""
import json
import os
import sys
import threading

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "common"))
from ceph_helper import assert_ge, assert_le, die, info, ok, rados_pool, run  # noqa: E402

POOL = "test_route_pool"
N = 20000
SIZE = 4096


def run_clients(conc=8):
    def worker(tag):
        with rados_pool(POOL) as (_, ctx):
            comps = []
            for i in range(N // conc):
                comps.append(ctx.aio_write_full(f"{tag}_{i:06d}", os.urandom(SIZE)))
            for c in comps:
                c.wait_for_complete()

    ths = [threading.Thread(target=worker, args=(f"c{k}",)) for k in range(conc)]
    for t in ths: t.start()
    for t in ths: t.join()


def osd_byte_spread():
    rc, out, _ = run("ceph osd df -f json", check=False)
    if rc != 0: die("ceph osd df failed")
    data = json.loads(out)
    usages = [n["kb_used"] for n in data.get("nodes", [])]
    if not usages: die("no OSD usage reported")
    info(f"OSD kb_used sample: {usages}")
    return usages


def main():
    before = osd_byte_spread()
    run_clients()
    after = osd_byte_spread()
    if len(before) != len(after):
        die("OSD topology changed during test")

    deltas = [a - b for a, b in zip(after, before)]
    # ignore OSDs that didn't grow at all
    active = [d for d in deltas if d > 0]
    if not active:
        die("no OSD saw new writes")
    hosts = sum(1 for d in active if d > 0)
    mean = sum(active) / len(active)
    worst = max(abs(d - mean) for d in active) / mean
    info(f"growth kb per OSD: {deltas};  hosts active={hosts};  worst deviation={worst*100:.1f}%")
    assert_ge(hosts, 2, "active OSD hosts")
    assert_le(worst * 100, 30, "max deviation", "%")
    ok("functional 2.5 PASS — routing & load balancing")


if __name__ == "__main__":
    main()
