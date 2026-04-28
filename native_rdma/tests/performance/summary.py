#!/usr/bin/env python3
"""Aggregate the latest perf_*.json reports into a single Markdown+JSON matrix.

Usage::

    python3 tests/performance/summary.py            # aggregates logs/perf/*.json
    python3 tests/performance/summary.py --dir X    # aggregates X/*.json

For each metric we pick the most recent file whose filename starts with the
metric id (perf_01_, perf_02_, ...) and compose a compact matrix::

    # Performance Matrix  (2026-04-27T21:30+08:00)
    | # | metric | key numbers | passed |
    |---|--------|-------------|--------|
    | 01 | ops_1kb | 1,060,928 ops/s, util 8.5%  | FAIL |
    | 02 | latency | avg=13.7us p99=20.7us       | PASS |
    ...
"""
from __future__ import annotations
import argparse
import glob
import json
import os
import sys
import time
from typing import Dict, Any, Optional, List


# Metric ordering and how to summarise each one.
METRIC_SUMMARY = {
    "perf_01": ("1KB PUT ops & bw utilization",
        lambda r: f"{int(r.get('ops_per_sec',0)):,} ops/s, "
                  f"bw={r.get('bw_gbps','?')} Gbps, "
                  f"util={r.get('util_pct','?')}%"),
    "perf_02": ("100k-object latency",
        lambda r: f"avg={r.get('lat_avg_us','?')}us "
                  f"p50={r.get('lat_p50_us','?')}us "
                  f"p99={r.get('lat_p99_us','?')}us "
                  f"samples={r.get('samples','?'):,}"
                  if isinstance(r.get('samples'), int)
                  else f"avg={r.get('lat_avg_us','?')}us "
                       f"p99={r.get('lat_p99_us','?')}us"),
    "perf_03": ("QoS high/low priority gain",
        lambda r: f"hi={int(r.get('hi_ops',0)):,} ops/s vs "
                  f"lo={int(r.get('lo_ops',0)):,} ops/s, "
                  f"gain={r.get('gain_pct','?')}% "
                  f"(threshold {r.get('threshold_gain_pct','?')}%)"),
    "perf_04": ("batch latency",
        lambda r: f"1000x100={r.get('batches_1000x100_ms','?')}ms, "
                  f"100x1000={r.get('batches_100x1000_ms','?')}ms"),
    "perf_05": ("batch throughput",
        lambda r: f"{r.get('mb_per_sec','?')} MB/s "
                  f"(threshold {r.get('threshold_mbs','?')})"),
    "perf_06": ("tier read/write bandwidth",
        lambda r: (f"write {r.get('write_gbs','?')} GB/s, "
                   f"read {r.get('read_gbs','?')} GB/s"
                   + (f"  ({r.get('note')})" if r.get('note') else ""))),
    "perf_08": ("Simulation engine 1M events realtime",
        lambda r: f"speedup={r.get('speedup','?')}x "
                  f"({int(r.get('events_per_sec',0)):,} events/s, "
                  f"{r.get('wall_s','?')}s wall, stress={r.get('stress','?')})"),
    "perf_09": ("mempool overhead/savings/scale",
        lambda r: f"overhead={r.get('overhead_pct','?')}%, "
                  f"savings={r.get('savings_pct','?')}%, "
                  f"scale={r.get('scale_gain_pct','?')}%"),
}

# Non-yet-implemented metrics; kept in the matrix as TODO so reports still
# reflect the full target list from docs/自研实施清单.md §7. Currently all
# metrics have at least a driver; this map is empty so the matrix shows
# the real PASS/FAIL state for every row.
METRIC_TODO = {}


def find_latest(dir_path: str, prefix: str) -> Optional[str]:
    files = sorted(glob.glob(os.path.join(dir_path, f"{prefix}_*.json")))
    return files[-1] if files else None


def load_json(path: str) -> Dict[str, Any]:
    try:
        with open(path) as f:
            return json.load(f)
    except Exception as e:
        return {"error": str(e)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir",
                    default=os.path.join(os.path.dirname(__file__),
                                         "..", "..", "logs", "perf"))
    ap.add_argument("--out-md",
                    default=None,
                    help="Output Markdown report path (defaults to logs/perf/matrix_<ts>.md)")
    args = ap.parse_args()

    dir_path = os.path.abspath(args.dir)
    os.makedirs(dir_path, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    out_md = args.out_md or os.path.join(dir_path, f"matrix_{ts}.md")
    out_json = os.path.join(dir_path, f"matrix_{ts}.json")

    matrix: List[Dict[str, Any]] = []
    lines: List[str] = []
    lines.append(f"# Performance Matrix  ({time.strftime('%Y-%m-%dT%H:%M:%S%z')})")
    lines.append("")
    lines.append("| # | metric | key numbers | passed |")
    lines.append("|---|--------|-------------|--------|")

    passed_cnt = 0
    total_cnt  = 0
    for mid in sorted(set(list(METRIC_SUMMARY.keys()) + list(METRIC_TODO.keys()))):
        total_cnt += 1
        if mid in METRIC_SUMMARY:
            name, fmt = METRIC_SUMMARY[mid]
            latest = find_latest(dir_path, mid)
            if latest:
                rec = load_json(latest)
                key_txt = fmt(rec) if "error" not in rec else f"ERROR: {rec['error']}"
                ok = bool(rec.get("passed", False))
                if ok: passed_cnt += 1
                verdict = "PASS" if ok else "FAIL"
                matrix.append({"id": mid, "name": name, "passed": ok,
                               "latest_file": latest, "record": rec})
                lines.append(f"| {mid[-2:]} | {name} | {key_txt} | **{verdict}** |")
            else:
                matrix.append({"id": mid, "name": name,
                               "passed": False, "latest_file": None,
                               "note": "no data yet; run the matching perf_*.sh"})
                lines.append(f"| {mid[-2:]} | {name} | _(no data)_ | - |")
        else:
            name, todo_note = METRIC_TODO[mid]
            matrix.append({"id": mid, "name": name, "passed": False,
                           "latest_file": None, "note": todo_note})
            lines.append(f"| {mid[-2:]} | {name} | _{todo_note}_ | TODO |")

    lines.append("")
    lines.append(f"**{passed_cnt}/{total_cnt} metrics passed.**")
    lines.append("")
    lines.append("## Raw files per metric")
    for m in matrix:
        if m.get("latest_file"):
            rel = os.path.relpath(m["latest_file"],
                                  os.path.dirname(os.path.dirname(__file__)))
            lines.append(f"- `{m['id']}`: `{rel}`")

    md_text = "\n".join(lines) + "\n"
    with open(out_md, "w") as f: f.write(md_text)
    with open(out_json, "w") as f:
        json.dump({"generated_at": ts, "passed": passed_cnt,
                   "total": total_cnt, "matrix": matrix}, f, indent=2)

    print(md_text)
    print(f"[summary] markdown: {out_md}")
    print(f"[summary] json    : {out_json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
