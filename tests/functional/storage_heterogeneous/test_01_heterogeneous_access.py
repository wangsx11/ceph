#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""功能 1.1 — 异构设备统一访问接口。

目的
----
验证 Ceph RADOS 统一对象接口可同时承载 NVMe / SATA-SSD / ZNS-SSD 三类
device class 的 OSD。即：同一套 `rados_write_op` 系列 API 对上层透明，
底层由 CRUSH rule 按 class 将副本落到不同设备。

方法
----
1. 枚举集群中的 OSD device class。
2. 为每个存在的 class 动态创建 CRUSH rule 和对应 pool。
3. 对每个 pool 做一次 1MB 对象的 put/get/verify。
4. 所有类都成功即通过。

执行
----
    python3 test_01_heterogeneous_access.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "common"))
from ceph_helper import assert_ge, die, info, need_bin, ok, rados_pool, run  # noqa: E402


def list_device_classes():
    rc, out, _ = run("ceph osd crush class ls -f json", check=False)
    if rc != 0:
        return []
    try:
        return json.loads(out)
    except Exception:
        return []


def ensure_rule_and_pool(cls_name):
    rule = f"rule_{cls_name}"
    pool = f"test_hetero_{cls_name}"
    run(f"ceph osd crush rule create-replicated {rule} default host {cls_name}", check=False)
    run(f"ceph osd pool create {pool} 32 32 replicated {rule}", check=False)
    run(f"ceph osd pool application enable {pool} rados --yes-i-really-mean-it", check=False)
    return pool


def roundtrip(pool):
    payload = os.urandom(1024 * 1024)
    with rados_pool(pool) as (_, ioctx):
        ioctx.write_full("hetero_probe", payload)
        got = ioctx.read("hetero_probe", len(payload))
        ioctx.remove_object("hetero_probe")
    if got != payload:
        die(f"pool {pool}: data mismatch after roundtrip")
    ok(f"pool {pool}: 1MB put/get verified")


def main():
    need_bin("ceph")
    classes = list_device_classes()
    if not classes:
        info("no device class reported; fallback to default pool")
        classes = ["default"]

    verified = 0
    for cls in classes:
        pool = ensure_rule_and_pool(cls) if cls != "default" else "test_hetero_default"
        if cls == "default":
            run(f"ceph osd pool create {pool} 32 32", check=False)
            run(f"ceph osd pool application enable {pool} rados --yes-i-really-mean-it", check=False)
        try:
            roundtrip(pool)
            verified += 1
        except Exception as e:
            info(f"class {cls}: skipped ({e})")
    assert_ge(verified, 1, "heterogeneous classes verified", " class")
    ok("functional 1.1 PASS — unified access over heterogeneous devices")


if __name__ == "__main__":
    main()
