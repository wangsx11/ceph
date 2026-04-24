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
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "common"))
from ceph_helper import die, info, ok, rados_pool, run  # noqa: E402

POOL = "ha_pool"
N = 200


def main():
    run(f"ceph osd pool create {POOL} 32 32", check=False)
    run(f"ceph osd pool set {POOL} size 3", check=False)
    run(f"ceph osd pool application enable {POOL} rados --yes-i-really-mean-it", check=False)

    digests = {}
    with rados_pool(POOL) as (_, ioctx):
        for i in range(N):
            data = os.urandom(4096)
            ioctx.write_full(f"ha_{i:04d}", data)
            digests[f"ha_{i:04d}"] = hashlib.sha256(data).hexdigest()

    # pick an OSD to kill
    rc, out, _ = run("ceph osd ls", check=False)
    osd_id = out.strip().splitlines()[0]
    info(f"stopping osd.{osd_id} …")
    run(f"sudo systemctl stop ceph-osd@{osd_id}", check=False)
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
        run(f"sudo systemctl start ceph-osd@{osd_id}", check=False)

    # wait for recovery
    for _ in range(60):
        rc, out, _ = run("ceph -s -f json", check=False)
        if '"HEALTH_OK"' in out:
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
