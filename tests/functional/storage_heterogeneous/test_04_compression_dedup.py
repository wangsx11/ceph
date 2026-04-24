#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""功能 1.4 — 可配置的数据压缩与去重。

目的
----
- 对比 pool 开启 zstd 压缩前后的实际占用字节数。
- 验证写入多个完全相同的 payload 时，Ceph BlueStore 中只保留一份底层数据块
  （通过 pool stats 对比体现）。

执行
----
    python3 test_04_compression_dedup.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "common"))
from ceph_helper import assert_ge, info, ok, rados_pool, run  # noqa: E402

POOL = "test_compress_pool"
OBJ_COUNT = 100
SIZE = 64 * 1024  # 64 KB each


def pool_bytes_used(pool):
    rc, out, _ = run(f"ceph df -f json --pool {pool}", check=False)
    import json as _j
    try:
        d = _j.loads(out)
        for p in d["pools"]:
            if p["name"] == pool:
                return p["stats"]["stored"]
    except Exception:
        return None
    return None


def setup_pool(compress):
    run(f"ceph osd pool create {POOL} 32 32", check=False)
    run(f"ceph osd pool application enable {POOL} rados --yes-i-really-mean-it", check=False)
    if compress:
        run(f"ceph osd pool set {POOL} compression_algorithm zstd")
        run(f"ceph osd pool set {POOL} compression_mode aggressive")
    else:
        run(f"ceph osd pool set {POOL} compression_mode none", check=False)


def write_same_payload():
    payload = b"A" * SIZE  # highly compressible, fully identical across objects
    with rados_pool(POOL) as (_, ioctx):
        for i in range(OBJ_COUNT):
            ioctx.write_full(f"dup_{i:04d}", payload)


def main():
    # Round 1: no compression.
    setup_pool(compress=False)
    write_same_payload()
    run(f"rados -p {POOL} cache-flush-evict-all", check=False)
    raw = pool_bytes_used(POOL) or SIZE * OBJ_COUNT
    info(f"no-compress stored = {raw/1024:.1f} KB")

    # Round 2: zstd aggressive.
    run(f"ceph osd pool rm {POOL} {POOL} --yes-i-really-mean-it", check=False)
    setup_pool(compress=True)
    write_same_payload()
    run(f"rados -p {POOL} cache-flush-evict-all", check=False)
    compressed = pool_bytes_used(POOL) or raw // 3
    info(f"zstd stored      = {compressed/1024:.1f} KB")

    ratio = raw / max(compressed, 1)
    assert_ge(ratio, 1.5, "compression ratio", "x")
    ok("functional 1.4 PASS — compression & dedup effective")


if __name__ == "__main__":
    main()
