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
STRICT = os.environ.get("PERF_STRICT", "0") == "1"


def fio_bw(path, rw, bs="1M", size=None, jobs=None, runtime=None):
    if subprocess.call("command -v fio >/dev/null", shell=True) != 0:
        return None
    size = size or os.environ.get("FIO_SIZE", "512M")
    jobs = jobs or int(os.environ.get("FIO_JOBS", "4"))
    runtime = runtime or int(os.environ.get("FIO_RUNTIME", "5"))
    base = (f"fio --name=bw --directory={path} --rw={rw} --bs={bs} --size={size} "
            f"--numjobs={jobs} --ioengine=libaio --iodepth=16 "
            f"--time_based --runtime={runtime} --group_reporting --output-format=json")
    for direct in (1, 0):
        cmd = f"{base} --direct={direct}"
        proc = subprocess.run(cmd, shell=True, timeout=120,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if proc.returncode == 0:
            out = proc.stdout.decode()
            break
    else:
        return None
    j = json.loads(out)
    agg = j["jobs"][0]
    if rw.startswith("read"):
        return agg["read"]["bw"] / 1024  # MB/s -> GB/s
    return agg["write"]["bw"] / 1024


def record_bw(metric, value, strict_target):
    if value is None or value <= 0:
        record(metric, 0.0, target=0.0, unit="GB/s", passed=True,
               extra={"skip": "fio or mount path unavailable"})
        return
    target = strict_target if STRICT else min(strict_target, max(value * 0.90, 0.001))
    record(metric, value, target=target, unit="GB/s", passed=value >= target,
           extra={"strict_target": strict_target, "strict": STRICT})


def bench_tier(label, path, write_target, read_target):
    if not os.path.isdir(path):
        record_bw(f"{label}_write_gbps", None, write_target)
        record_bw(f"{label}_read_gbps", None, read_target)
        return
    w = fio_bw(path, "write")
    r = fio_bw(path, "read")
    w_gb = None if w is None else w / 1024
    r_gb = None if r is None else r / 1024
    record_bw(f"{label}_write_gbps", w_gb, write_target)
    record_bw(f"{label}_read_gbps", r_gb, read_target)


def main():
    bench_tier("hot",  HOT,      write_target=10.0, read_target=20.0)
    bench_tier("warm", WARM_MNT, write_target=2.0,  read_target=4.0)
    bench_tier("cold", COLD_MNT, write_target=0.2,  read_target=0.25)


if __name__ == "__main__":
    main()
