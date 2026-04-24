#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""性能指标 1 — RDMA 网络带宽利用率 + 1KB 吞吐 100 万/s。

方法
----
1. 用 `ib_write_bw` 测得链路实际带宽（MB/s）。
2. 用 `rados bench` 1KB 并发写测得 ops/s，把字节数换算回 MB/s，
   取其与链路带宽的比值作为"带宽利用率"。
"""
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "common"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from _report import record  # noqa: E402
from ceph_helper import rdma_port_rate_gbps, run  # noqa: E402

POOL = "perf_pool"


def bench_1kb():
    cmd = f"rados bench -p {POOL} 20 write -b 1024 -t 64 --no-cleanup"
    rc, out, _ = run(cmd, check=False, timeout=120)
    if rc != 0:
        return 0, 0
    ops = bw_mb = 0
    for line in out.splitlines():
        m = re.match(r"Total writes made:\s+(\d+)", line)
        if m: ops = int(m.group(1))
        m = re.match(r"Bandwidth \(MB/sec\):\s+([\d\.]+)", line)
        if m: bw_mb = float(m.group(1))
    return ops / 20.0, bw_mb


def main():
    link_gbps = rdma_port_rate_gbps() or 100.0
    link_mbps = link_gbps * 1024 / 8

    ops, bw = bench_1kb()
    util = bw / link_mbps * 100
    record("rdma_bw_util_pct", util, target=50.0, unit="%", passed=util >= 50)
    record("ops_per_sec_1kb", ops, target=1_000_000, unit=" ops/s",
           passed=ops >= 1_000_000)


if __name__ == "__main__":
    main()
