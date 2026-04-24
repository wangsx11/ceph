#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""功能 3.5 — 任务 / 用户级隔离。

使用 Ceph cephx cap + namespace 实现：
    cap osd "allow rw pool=mempool_shared namespace=task_A"
用户 A 的 keyring 只能访问 task_A；访问 task_B 时应被拒绝。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "common"))
from ceph_helper import info, ok, run  # noqa: E402

POOL = "mempool_shared"


def main():
    run(f"ceph osd pool create {POOL} 32 32", check=False)
    run(f"ceph osd pool application enable {POOL} rados --yes-i-really-mean-it", check=False)

    # create two capability-limited users
    run(f"ceph auth get-or-create client.task_A "
        f"mon 'allow r' "
        f"osd 'allow rw pool={POOL} namespace=task_A' "
        f"-o /tmp/ceph.client.task_A.keyring", check=False)
    run(f"ceph auth get-or-create client.task_B "
        f"mon 'allow r' "
        f"osd 'allow rw pool={POOL} namespace=task_B' "
        f"-o /tmp/ceph.client.task_B.keyring", check=False)

    # A writes into its own namespace
    rc, _, err = run(
        f"rados -p {POOL} -N task_A "
        f"--name client.task_A --keyring /tmp/ceph.client.task_A.keyring "
        f"put probe_A /etc/hostname",
        check=False)
    if rc != 0:
        info(f"task_A write failed: {err}")
        sys.exit(1)

    # A tries to access task_B — should fail
    rc, _, _ = run(
        f"rados -p {POOL} -N task_B "
        f"--name client.task_A --keyring /tmp/ceph.client.task_A.keyring "
        f"put probe_X /etc/hostname",
        check=False)
    if rc == 0:
        info("isolation BROKEN — task_A wrote into task_B")
        sys.exit(1)
    ok("functional 3.5 PASS — task/user isolation")


if __name__ == "__main__":
    main()
