#!/usr/bin/env python3
"""PF-5: RDMA 网络环境下批处理能力

Threshold: 批处理传输速度 >= 700MB/s (1KB objects)
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


PF_ID = "PF-5"
PF_NAME = "RDMA 网络环境下批处理能力"
SOURCE_NO = 5
THRESHOLD = "批处理传输速度 >= 700MB/s"
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
    m = re.search(rf"ops/s\s*:\s*({NUM})", text)
    if m:
        out["ops_per_sec"] = float(m.group(1))
    m = re.search(r"ops ok/fail\s*:\s*(\d+)\s*/\s*(\d+)", text)
    if m:
        out["ops_ok"] = int(m.group(1))
        out["ops_fail"] = int(m.group(2))
    m = re.search(r"ops degraded\s*:\s*(\d+)", text)
    if m:
        out["ops_degraded"] = int(m.group(1))
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
        f"- Key Result: {result.get('mb_per_sec', 'N/A')} MB/s",
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
    for key in ("mb_per_sec", "ops_per_sec", "val_size", "threshold_mbs",
                "ops_fail", "ops_degraded"):
        lines.append(f"| `{key}` | {result.get(key, 'N/A')} |")
    lines.extend([
        "",
        "## 统计口径",
        "",
        "- `mb_per_sec = ops_per_sec * val_size / 1,000,000`。",
        "- 使用 batch PUT 模式提升吞吐。",
        "- 不统计构建、脚本启动、环境启动和 warmup 时间。",
    ])
    note = result.get("error") or result.get("note")
    if note:
        lines.extend(["", "## 说明", "", str(note)])
    (path / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def fail_early(path: Path, message: str, code: int = 2) -> int:
    logs = log_dir()
    result = {"metric": "perf_05_batch_bw", "passed": False, "error": message}
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
    bin_path = resolve_cmake_bin(root, "nr_bench")
    uds = os.environ.get("UDS", "/tmp/native_rdma-dp.sock")
    dur = os.environ.get("DUR", "15")
    threads = os.environ.get("THREADS", "4")
    batch = os.environ.get("BATCH", "64")
    require_peer = os.environ.get("REQUIRE_PEER", "1")
    raw_json = path / "raw.json"
    run_log = logs / "run.log"

    if not os.access(bin_path, os.X_OK):
        return fail_early(path, f"nr_bench missing: {bin_path}")
    if not can_connect_uds(uds):
        return fail_early(path, f"data plane UDS is not connectable: {uds}; this test requires the data plane.")

    run_lines: list[str] = []

    # Warmup
    warmup_cmd = [
        str(bin_path), f"--uds={uds}", "--op=put", f"--threads={threads}",
        "--val-size=1024", "--duration=3", f"--batch={batch}",
    ]
    proc = subprocess.run(warmup_cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    run_lines.append(f"[warmup] $ {' '.join(warmup_cmd)}\nexit={proc.returncode}\n{proc.stdout}\n")

    # Measured run with batch PUT
    cmd = [
        str(bin_path), f"--uds={uds}", "--op=put", f"--threads={threads}",
        "--val-size=1024", f"--duration={dur}", f"--require-peer={require_peer}",
        f"--batch={batch}",
    ]
    proc = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    run_lines.append(f"[measured] $ {' '.join(cmd)}\nexit={proc.returncode}\n{proc.stdout}\n")
    parsed = parse_bench_output(proc.stdout)

    ops = float(parsed.get("ops_per_sec", 0))
    size = int(parsed.get("val_size", 1024))
    fail_count = int(parsed.get("ops_fail", 0))
    degraded = int(parsed.get("ops_degraded", 0))
    ops_ok = int(parsed.get("ops_ok", 0))
    total = ops_ok + fail_count
    fail_pct = (fail_count / total * 100.0) if total > 0 else 0.0
    mbps = ops * size / 1e6

    result = {
        "metric": "perf_05_batch_bw",
        "ops_per_sec": ops,
        "ops_fail": fail_count,
        "ops_degraded": degraded,
        "val_size": size,
        "mb_per_sec": round(mbps, 2),
        "threshold_mbs": 700.0,
        "passed": bool(mbps >= 700.0 and fail_pct < 10.0 and degraded == 0),
        "raw": parsed,
    }
    if proc.returncode != 0:
        result["note"] = f"nr_bench exited with {proc.returncode}"

    ts = time.strftime("%Y%m%d_%H%M%S")
    write_json(logs / f"perf_05_batch_bw_{ts}.json", result)
    write_json(raw_json, result)
    run_log.write_text("\n".join(run_lines), encoding="utf-8")
    write_summary(path, result, run_log, raw_json)
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
