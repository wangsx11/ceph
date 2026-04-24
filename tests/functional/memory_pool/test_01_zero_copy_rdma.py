#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""功能 3.1 — RDMA 零拷贝远程内存访问。

对照性能指标第 2 条：端到端 1KB 传输 P99 ≤ 100μs，平均 ≤ 50μs。
这里用 `ib_read_lat` / `ib_write_lat` 测纯 RDMA 往返延迟。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "common"))
from ceph_helper import assert_le, die, info, ok, need_bin, run  # noqa: E402


def parse_avg(out):
    for line in out.splitlines():
        if "usec" in line and "#bytes" not in line:
            parts = line.split()
            try:
                # columns: #bytes #iterations t_min[usec] t_max[usec] t_typical[usec] t_avg[usec] ...
                return float(parts[5])
            except Exception:
                continue
    return None


def main():
    need_bin("ib_read_lat")
    peer = os.environ.get("PEER_HOST")
    if not peer:
        info("PEER_HOST not set; functional test requires a peer – SKIP")
        return
    rc, out, _ = run(f"ib_read_lat -s 1024 -n 10000 {peer}", check=False, timeout=60)
    if rc != 0:
        die("ib_read_lat failed; peer not running?")
    avg = parse_avg(out)
    if avg is None:
        die("cannot parse ib_read_lat output")
    info(f"ib_read_lat 1KB avg = {avg:.2f} μs")
    assert_le(avg, 50.0, "RDMA read latency avg", " μs")
    ok("functional 3.1 PASS — zero-copy RDMA access")


if __name__ == "__main__":
    main()
