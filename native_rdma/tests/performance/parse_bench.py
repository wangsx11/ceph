#!/usr/bin/env python3
"""Parse a single ``nr_bench`` textual report into a dict.

The nr_bench binary prints blocks like::

    ==== nr_bench result ====
      elapsed       : 10.00 s
      threads       : 8
      op            : put
      ops ok/fail   : 3593723 / 0
      ops/s         : 359356
      latency us    : avg=21.73  p50=21.02  p99=32.11  p99.9=40.97  max=6345.06

We pull every numeric field into a flat dict suitable for emitting JSON.
"""
from __future__ import annotations
import re
import sys
from typing import Dict, Any


_NUM = r"[-+]?\d+(?:\.\d+)?"


def parse_bench_output(text: str) -> Dict[str, Any]:
    """Extract all interesting fields from a single nr_bench report block."""
    out: Dict[str, Any] = {}
    m = re.search(rf"elapsed\s*:\s*({_NUM})", text)
    if m: out["elapsed_s"] = float(m.group(1))
    m = re.search(rf"threads\s*:\s*(\d+)", text)
    if m: out["threads"] = int(m.group(1))
    m = re.search(r"op\s*:\s*(\w+)", text)
    if m: out["op"] = m.group(1)
    m = re.search(r"ops ok/fail\s*:\s*(\d+)\s*/\s*(\d+)", text)
    if m:
        out["ops_ok"]   = int(m.group(1))
        out["ops_fail"] = int(m.group(2))
    m = re.search(rf"ops/s\s*:\s*({_NUM})", text)
    if m: out["ops_per_sec"] = float(m.group(1))
    m = re.search(rf"latency us\s*:\s*avg=({_NUM})\s+p50=({_NUM})\s+p99=({_NUM})\s+p99\.9=({_NUM})\s+max=({_NUM})", text)
    if m:
        out["lat_avg_us"]   = float(m.group(1))
        out["lat_p50_us"]   = float(m.group(2))
        out["lat_p99_us"]   = float(m.group(3))
        out["lat_p99_9_us"] = float(m.group(4))
        out["lat_max_us"]   = float(m.group(5))
    # Real bytes moved over UDS (added in nr_bench W5-fix). Falls back to
    # missing keys when running an older nr_bench -- callers should handle
    # absence gracefully.
    m = re.search(rf"req_bytes\s*:\s*(\d+)\s*\(({_NUM})\s*MB/s\)", text)
    if m:
        out["req_bytes"]    = int(m.group(1))
        out["req_mbps"]     = float(m.group(2))
    m = re.search(rf"resp_bytes\s*:\s*(\d+)\s*\(({_NUM})\s*MB/s\)", text)
    if m:
        out["resp_bytes"]   = int(m.group(1))
        out["resp_mbps"]    = float(m.group(2))
    # Recover val_size from the "nr_bench" header line that lives above the
    # report block (printed at startup).
    m = re.search(r"val_size=(\d+)", text)
    if m: out["val_size"] = int(m.group(1))
    return out


if __name__ == "__main__":
    data = sys.stdin.read()
    result = parse_bench_output(data)
    import json
    print(json.dumps(result, indent=2))
