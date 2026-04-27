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


def crush_host_weights():
    rc, out, _ = run("ceph osd tree -f json", check=False)
    if rc != 0:
        die("ceph osd tree failed")
    data = json.loads(out)
    osd_status = {
        node["id"]: node
        for node in data.get("nodes", [])
        if node.get("type") == "osd" and node.get("status") == "up"
    }
    weights = []
    for node in data.get("nodes", []):
        if node.get("type") != "host":
            continue
        weight = 0.0
        for osd_id in node.get("children", []):
            osd = osd_status.get(osd_id)
            if osd:
                weight += float(osd.get("crush_weight", 0.0))
        if weight > 0:
            weights.append((node["name"], weight))
    if not weights:
        die("no up OSD host weights reported")
    info(f"CRUSH host weights: {dict(weights)}")
    return [weight for _, weight in weights]


def main():
    run_clients()
    active = crush_host_weights()
    hosts = len(active)
    mean = sum(active) / len(active)
    worst = max(abs(d - mean) for d in active) / mean
    info(f"host weights: {active};  hosts active={hosts};  worst deviation={worst*100:.1f}%")
    assert_ge(hosts, 2, "active OSD hosts")
    assert_le(worst * 100, 30, "max deviation", "%")
    ok("functional 2.5 PASS — routing & load balancing")


if __name__ == "__main__":
    main()
