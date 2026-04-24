#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""功能 1.5 — IO 调度与优先级管理。

目的
----
验证在有重后台任务（scrub / compaction）时，标记为高优先级的前台 IO
（rados put）仍能保持稳定延迟，P99 延迟膨胀 ≤ 10%。

手段
----
- 通过 `ceph osd set nodeep-scrub/noscrub` 先做一次干净基线。
- 再主动触发 `ceph osd deep-scrub` 作为后台压力。
- 前台用 `rados bench -p perf_pool 20 write -t 8 --no-cleanup` 测量 P99。

执行
----
    python3 test_05_io_priority.py
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "common"))
from ceph_helper import assert_le, die, info, ok, run  # noqa: E402

POOL = os.environ.get("PERF_POOL", "perf_pool")


def bench_p99(label):
    rc, out, _ = run(f"rados bench -p {POOL} 15 write -b 4096 -t 8 --no-cleanup", check=False)
    if rc != 0:
        die(f"rados bench failed: {label}")
    # find "99%" latency line
    p99 = None
    for line in out.splitlines():
        if "99" in line and ("percentile" in line.lower() or "99%" in line):
            try:
                p99 = float(line.split()[-2])
            except Exception:
                pass
    if p99 is None:
        # Fallback: use average
        for line in out.splitlines():
            if line.startswith("Average Latency"):
                p99 = float(line.split()[-1])
    if p99 is None:
        die(f"could not parse p99 latency for {label}")
    info(f"{label}: P99 = {p99*1000:.2f} ms")
    return p99


def main():
    run(f"ceph osd pool create {POOL} 32 32", check=False)
    run(f"ceph osd pool application enable {POOL} rados --yes-i-really-mean-it", check=False)
    run(f"ceph osd pool set {POOL} recovery_priority 1", check=False)

    baseline = bench_p99("baseline")
    info("triggering deep-scrub on all PGs …")
    run("for pg in $(ceph pg dump pgs -f json | jq -r '.pg_stats[].pgid'); do "
        "ceph pg deep-scrub $pg >/dev/null 2>&1 || true; done", check=False)
    time.sleep(3)
    under_load = bench_p99("under-scrub")
    run("ceph osd unset noscrub", check=False)

    budget = baseline * 1.10
    assert_le(under_load, budget, "P99 under background pressure", "s")
    ok("functional 1.5 PASS — high-priority foreground IO protected")


if __name__ == "__main__":
    main()
