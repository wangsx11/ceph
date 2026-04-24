#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""功能 3.3 — 内存池统一命名机制。

在节点 A 创建 namespace `sim.training.tank`，在节点 B 以同名挂载后
应能看到 A 写入的对象。基于 RADOS namespace 能力实现。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "common"))
from ceph_helper import die, info, ok, rados_pool  # noqa: E402

POOL = "mempool_shared"
NS = "sim.training.tank"


def main():
    payload = os.urandom(4096)
    # producer
    with rados_pool(POOL) as (_, ioctx):
        ioctx.set_namespace(NS)
        ioctx.write_full("entity_0001", payload)

    # consumer (same process simulates peer-node)
    with rados_pool(POOL) as (_, ioctx):
        ioctx.set_namespace(NS)
        got = ioctx.read("entity_0001")
    if got != payload:
        die("namespaced read mismatch")

    # different namespace must NOT see it
    with rados_pool(POOL) as (_, ioctx):
        ioctx.set_namespace("other.ns")
        try:
            ioctx.read("entity_0001")
            die("isolation violated — other namespace read the object")
        except Exception:
            info("other namespace correctly denied")
    ok("functional 3.3 PASS — unified naming & namespaces")


if __name__ == "__main__":
    main()
