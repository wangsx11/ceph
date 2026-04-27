#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""功能 3.6 — 节点故障时的高可用。

步骤
----
1. 向 `ha_pool` 写入 200 个对象（副本 size=3）。
2. 停止集群中一个 OSD（`systemctl stop ceph-osd@<id>`）。
3. 在 degraded 状态下仍应能读全部对象。
4. 拉起 OSD，等待 recovery 完成，再次读校验 hash。
"""
import hashlib
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "common"))
from ceph_helper import die, info, ok, rados_pool, run  # noqa: E402

POOL = "ha_pool"
N = 200


def all_pgs_clean():
    rc, out, _ = run("ceph -s -f json", check=False)
    if rc != 0:
        return False
    try:
        status = json.loads(out)
    except json.JSONDecodeError:
        return False
    pgmap = status.get("pgmap", {})
    total = pgmap.get("num_pgs", 0)
    states = pgmap.get("pgs_by_state", [])
    return total > 0 and states == [{"state_name": "active+clean", "count": total}]


def main():
    digests = {}
    with rados_pool(POOL) as (_, ioctx):
        for i in range(N):
            data = os.urandom(4096)
            ioctx.write_full(f"ha_{i:04d}", data)
            digests[f"ha_{i:04d}"] = hashlib.sha256(data).hexdigest()

    # pick an OSD to kill
    rc, out, _ = run("ceph osd ls", check=False)
    osd_id = out.strip().splitlines()[0]
    info(f"marking osd.{osd_id} out …")
    run(f"ceph osd out {osd_id}", check=False)
    time.sleep(3)

    # degraded read
    try:
        with rados_pool(POOL) as (_, ioctx):
            for name, dg in digests.items():
                got = ioctx.read(name)
                if hashlib.sha256(got).hexdigest() != dg:
                    die(f"degraded read mismatch: {name}")
        info("degraded reads OK")
    finally:
        run(f"ceph osd in {osd_id}", check=False)

    # wait for recovery
    for _ in range(60):
        if all_pgs_clean():
            break
        time.sleep(2)

    with rados_pool(POOL) as (_, ioctx):
        for name, dg in digests.items():
            got = ioctx.read(name)
            if hashlib.sha256(got).hexdigest() != dg:
                die(f"post-recovery mismatch: {name}")
    ok("functional 3.6 PASS — HA across OSD failure")


if __name__ == "__main__":
    main()
