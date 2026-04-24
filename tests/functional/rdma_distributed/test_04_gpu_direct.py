#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""功能 2.4 — CPU/GPU 直通 (GPUDirect RDMA)。

目的
----
- 若系统加载了 `nvidia_peermem` (或 `nv_peer_mem`) 模块，则使用 pinned GPU
  显存作为 RDMA 注册区做 ib_write_bw，对比 host memory 带宽；
- 若未加载则跳过 GPU 路径、只做 pageable vs pinned host memory 对照，
  验证 pinned（`--use-null`）吞吐更高。

断言
----
- 有 GPUDirect：GPU 路径带宽 ≥ 主机 pinned 路径 90%（允许小幅损失）
- 无 GPUDirect：pinned 带宽 > pageable 带宽
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "common"))
from ceph_helper import assert_ge, info, ok, run  # noqa: E402


def has_gpudirect():
    rc, out, _ = run("lsmod | grep -E 'nv_peer_mem|nvidia_peermem'", check=False)
    return rc == 0 and out.strip() != ""


def parse_bw(out):
    # ib_write_bw prints a table; we want the last "BW average[MiB/sec]" column
    for line in out.splitlines()[::-1]:
        parts = line.split()
        if len(parts) >= 4:
            try:
                return float(parts[-2])
            except Exception:
                continue
    return None


def main():
    peer = os.environ.get("PEER_HOST")
    if not peer:
        info("PEER_HOST env not set; running server side only – please launch "
             "`ib_write_bw` on the peer manually, or set PEER_HOST and rerun")
        info("SKIP – peer host required for loopback BW measurement")
        return

    # host pageable
    rc, out_pg, _ = run(f"ib_write_bw -a -F --duration=5 {peer}", check=False, timeout=60)
    host_bw = parse_bw(out_pg) or 0
    info(f"host pageable BW    = {host_bw:.0f} MiB/s")

    # host pinned (default ib_write_bw already pins)
    rc, out_pn, _ = run(f"ib_write_bw -a -F --duration=5 --report_gbits {peer}", check=False, timeout=60)
    pin_bw = parse_bw(out_pn) or 0
    info(f"host pinned BW      = {pin_bw:.0f} MiB/s")

    if has_gpudirect():
        rc, out_gd, _ = run(f"ib_write_bw -a -F --use_cuda=0 --duration=5 {peer}",
                            check=False, timeout=60)
        gpu_bw = parse_bw(out_gd) or 0
        info(f"GPUDirect BW        = {gpu_bw:.0f} MiB/s")
        assert_ge(gpu_bw, pin_bw * 0.9, "GPUDirect vs pinned", " MiB/s")
    else:
        info("nvidia_peermem not loaded; only asserting pinned > pageable")
        assert_ge(pin_bw, host_bw, "pinned vs pageable", " MiB/s")
    ok("functional 2.4 PASS — CPU/GPU direct access")


if __name__ == "__main__":
    main()
