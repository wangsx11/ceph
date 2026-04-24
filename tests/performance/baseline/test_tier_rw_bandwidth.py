#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""性能指标 6 — 多级存储读写带宽。

使用 fio 对热层 (ramfs)、温层 (SSD osd)、冷层 (HDD osd) 分别跑顺序读写：

- 写目标 10 GB/s、读目标 20 GB/s（全闪存阵列总和）

执行需要 root 或已配置的 fio；脚本会在无 fio 时记录 SKIP。
"""
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "common"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from _report import record  # noqa: E402

HOT = os.environ.get("HOT_PATH", "/mnt/hot")
WARM_MNT = os.environ.get("WARM_MNT", "/mnt/warm")
COLD_MNT = os.environ.get("COLD_MNT", "/mnt/cold")


def fio_bw(path, rw, bs="1M", size="8G", jobs=16):
    if subprocess.call("command -v fio >/dev/null", shell=True) != 0:
        return None
    cmd = (f"fio --name=bw --directory={path} --rw={rw} --bs={bs} --size={size} "
           f"--numjobs={jobs} --ioengine=libaio --direct=1 --iodepth=32 "
           f"--time_based --runtime=15 --group_reporting --output-format=json")
    out = subprocess.check_output(cmd, shell=True, timeout=120).decode()
    j = json.loads(out)
    agg = j["jobs"][0]
    if rw.startswith("read"):
        return agg["read"]["bw"] / 1024  # MB/s -> GB/s
    return agg["write"]["bw"] / 1024


def bench_tier(label, path, write_target, read_target):
    if not os.path.isdir(path):
        print(f"[SKIP] {label} path {path} not available")
        return
    w = fio_bw(path, "write") or 0
    r = fio_bw(path, "read") or 0
    w_gb = w / 1024; r_gb = r / 1024  # MB->GB
    record(f"{label}_write_gbps", w_gb, target=write_target, unit="GB/s",
           passed=w_gb >= write_target)
    record(f"{label}_read_gbps",  r_gb, target=read_target,  unit="GB/s",
           passed=r_gb >= read_target)


def main():
    bench_tier("hot",  HOT,      write_target=10.0, read_target=20.0)
    bench_tier("warm", WARM_MNT, write_target=2.0,  read_target=4.0)
    bench_tier("cold", COLD_MNT, write_target=0.2,  read_target=0.25)


if __name__ == "__main__":
    main()
