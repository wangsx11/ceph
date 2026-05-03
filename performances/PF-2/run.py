#!/usr/bin/env python3
"""PF-2: RDMA 网络环境下对象传输能力

Thresholds:
  - 至少 100,000 个 1KB 对象成功传输
  - 平均时延 <= 50us
  - P99 <= 100us
  - 失败数 == 0, 降级数 == 0
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import can_connect_uds, resolve_cmake_bin


PF_ID = "PF-2"
PF_NAME = "RDMA 网络环境下对象传输能力"
SOURCE_NO = 2
THRESHOLD = "平均时延 <= 50us；P99 <= 100us；样本数 >= 100,000"
NUM = r"[-+]?\d+(?:\.\d+)?"


def repo_root() -> Path:
    return Path(os.environ.get("REPO_ROOT", Path(__file__).resolve().parents[2])).resolve()


def out_dir() -> Path:
    path = Path(os.environ.get("OUT_DIR", Path(__file__).resolve().parent)).resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


def log_dir() -> Path:
    path = out_dir() / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def parse_bench_output(text: str) -> dict:
    out: dict = {}
    m = re.search(rf"elapsed\s*:\s*({NUM})", text)
    if m:
        out["elapsed_s"] = float(m.group(1))
    m = re.search(r"threads\s*:\s*(\d+)", text)
    if m:
        out["threads"] = int(m.group(1))
    m = re.search(r"ops ok/fail\s*:\s*(\d+)\s*/\s*(\d+)", text)
    if m:
        out["ops_ok"] = int(m.group(1))
        out["ops_fail"] = int(m.group(2))
    m = re.search(r"ops degraded\s*:\s*(\d+)", text)
    if m:
        out["ops_degraded"] = int(m.group(1))
    m = re.search(rf"ops/s\s*:\s*({NUM})", text)
    if m:
        out["ops_per_sec"] = float(m.group(1))
    m = re.search(
        rf"latency us\s*:\s*avg=({NUM})\s+p50=({NUM})"
        rf"(?:\s+p90=({NUM}))?\s+p99=({NUM})\s+p99\.9=({NUM})\s+max=({NUM})",
        text,
    )
    if m:
        out["lat_avg_us"] = float(m.group(1))
        out["lat_p50_us"] = float(m.group(2))
        out["lat_p99_us"] = float(m.group(4))
        out["lat_p99_9_us"] = float(m.group(5))
        out["lat_max_us"] = float(m.group(6))
    m = re.search(r"val_size=(\d+)", text)
    if m:
        out["val_size"] = int(m.group(1))
    return out


def write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def write_summary(path: Path, result: dict, run_log: Path, raw_json: Path) -> None:
    lines = [
        f"# {PF_ID} Summary",
        "",
        f"- Metric: {PF_NAME}",
        f"- Source: `docs/性能要求.md` 第 {SOURCE_NO} 条",
        f"- Generated At: {time.strftime('%Y-%m-%dT%H:%M:%S%z')}",
        f"- Samples: {result.get('samples', 0)}/100000",
        f"- Key Result: avg={result.get('lat_avg_us', 'N/A')}us, p99={result.get('lat_p99_us', 'N/A')}us",
        f"- Threshold: {THRESHOLD}",
        f"- Result: {'PASS' if result.get('passed') else 'FAIL'}",
        f"- Result Dir: {path.resolve()}",
        f"- Raw JSON: {raw_json.resolve()}",
        f"- Run Log: {run_log.resolve()}",
        "",
        "## 关键统计值",
        "",
        "| Key | Value |",
        "|---|---:|",
    ]
    for key in ("samples", "lat_avg_us", "lat_p50_us", "lat_p99_us", "lat_p99_9_us", "lat_max_us", "ops_fail", "ops_degraded"):
        lines.append(f"| `{key}` | {result.get(key, 'N/A')} |")
    lines.extend([
        "",
        "## 统计口径",
        "",
        "- 统计 measured 窗口内成功 1KB 对象的数据面端到端传输时延。",
        "- 使用 PUT 操作衡量对象传输能力（写入本地 slab + RDMA 异步复制）。",
        "- 失败样本单独计数，不混入成功样本分位数。",
        "- 不统计构建、脚本启动、环境启动和 warmup 时间。",
    ])
    note = result.get("error") or result.get("note")
    if note:
        lines.extend(["", "## 说明", "", str(note)])
    (path / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def fail_early(path: Path, message: str, code: int = 2) -> int:
    logs = log_dir()
    result = {"metric": "perf_02_latency", "passed": False, "error": message}
    raw_json = path / "raw.json"
    run_log = logs / "run.log"
    write_json(raw_json, result)
    run_log.write_text(message + "\n", encoding="utf-8")
    write_summary(path, result, run_log, raw_json)
    return code


def main() -> int:
    root = repo_root()
    path = out_dir()
    logs = log_dir()
    native_root = root / "native_rdma"
    bin_path = resolve_cmake_bin(root, "nr_bench")
    uds = os.environ.get("UDS", "/tmp/native_rdma-dp.sock")
    dur = os.environ.get("DUR", "10")
    threads = os.environ.get("THREADS", "8")
    require_peer = os.environ.get("REQUIRE_PEER", "1")
    raw_json = path / "raw.json"
    run_log = logs / "run.log"

    if not os.access(bin_path, os.X_OK):
        return fail_early(path, f"nr_bench missing: {bin_path}")
    if not can_connect_uds(uds):
        return fail_early(path, f"data plane UDS is not connectable: {uds}; this test requires the data plane.")

    run_lines: list[str] = []

    # Warmup: stabilize heartbeat + memory pools (not measured)
    warmup_cmd = [
        str(bin_path), f"--uds={uds}", "--op=put", f"--threads={threads}",
        "--val-size=1024", "--duration=3",
    ]
    proc = subprocess.run(warmup_cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    run_lines.append(f"[warmup] $ {' '.join(warmup_cmd)}\nexit={proc.returncode}\n{proc.stdout}\n")

    # Measured run: PUT 1KB objects, measure latency
    cmd = [
        str(bin_path), f"--uds={uds}", "--op=put", f"--threads={threads}",
        "--val-size=1024", f"--duration={dur}", f"--require-peer={require_peer}",
    ]
    proc = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    run_lines.append(f"[measured] $ {' '.join(cmd)}\nexit={proc.returncode}\n{proc.stdout}\n")
    parsed = parse_bench_output(proc.stdout)

    avg = float(parsed.get("lat_avg_us", 1e9))
    p99 = float(parsed.get("lat_p99_us", 1e9))
    ok = int(parsed.get("ops_ok", 0))
    fail_count = int(parsed.get("ops_fail", 0))
    degraded = int(parsed.get("ops_degraded", 0))

    passed = bool(
        ok >= 100_000
        and avg <= 50.0
        and p99 <= 100.0
        and fail_count == 0
        and degraded == 0
    )

    result = {
        "metric": "perf_02_latency",
        "samples": ok,
        "ops_fail": fail_count,
        "ops_degraded": degraded,
        "lat_avg_us": avg,
        "lat_p50_us": float(parsed.get("lat_p50_us", 0)),
        "lat_p99_us": p99,
        "lat_p99_9_us": float(parsed.get("lat_p99_9_us", 0)),
        "lat_max_us": float(parsed.get("lat_max_us", 0)),
        "thresholds": {"samples": 100_000, "avg_us": 50.0, "p99_us": 100.0},
        "passed": passed,
        "raw": parsed,
    }
    if proc.returncode != 0:
        result["note"] = f"nr_bench exited with {proc.returncode}"

    ts = time.strftime("%Y%m%d_%H%M%S")
    write_json(logs / f"perf_02_latency_{ts}.json", result)
    write_json(raw_json, result)
    run_log.write_text("\n".join(run_lines), encoding="utf-8")
    write_summary(path, result, run_log, raw_json)
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
