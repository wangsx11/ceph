#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""功能 3.2 — 分布式内存池 API。

验证 `rdma_mempool` 提供的封装 API：
    mp = MemPool("sim_region", size_mb=64)
    h  = mp.alloc(1024)        # 返回句柄
    mp.write(h, payload)
    data = mp.read(h)
    mp.free(h)
"""
import hashlib
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "backend_v2"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "common"))

from ceph_helper import die, ok  # noqa: E402


def main():
    from rdma_mempool import MemPool  # lazy import from backend_v2

    mp = MemPool("test_mempool_region", size_mb=16)
    handles = []
    payloads = []
    for i in range(100):
        data = os.urandom(1024)
        h = mp.alloc(1024)
        mp.write(h, data)
        handles.append(h)
        payloads.append(data)

    # readback
    for h, want in zip(handles, payloads):
        got = mp.read(h)
        if hashlib.sha256(got).digest() != hashlib.sha256(want).digest():
            die(f"read mismatch on handle {h}")
    # free
    for h in handles:
        mp.free(h)

    ok("functional 3.2 PASS — mempool api round-trip")


if __name__ == "__main__":
    main()
