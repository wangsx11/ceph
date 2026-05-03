#!/usr/bin/env python3
"""PF-4: RDMA 网络环境下对象数据聚合传输能力

场景 A: 1000 批次 × 100 个 1KB 对象，串行执行，总耗时 <= 200ms
场景 B: 100 批次 × 1000 个 1KB 对象，串行执行，总耗时 <= 100ms

使用 nr_bench --count 模式精确执行指定数量的串行批次。
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


PF_ID = "PF-4"
PF_NAME = "RDMA 网络环境下对象数据聚合传输能力"
SOURCE_NO = 4
THRESHOLD = "场景 A (1000×100) <= 200ms；场景 B (100×1000) <= 100ms"
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
    m = re.search(rf"elapsed_ms\s*:\s*({NUM})", text)
    if m:
        out["elapsed_ms"] = float(m.group(1))
    m = re.search(r"ops ok/fail\s*:\s*(\d+)\s*/\s*(\d+)", text)
    if m:
        out["ops_ok"] = int(m.group(1))
        out["ops_fail"] = int(m.group(2))
    m = re.search(r"ops degraded\s*:\s*(\d+)", text)
    if m:
        out["ops_degraded"] = int(m.group(1))
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
        f"- Threshold: {THRESHOLD}",
        f"- Result: {'PASS' if result.get('passed') else 'FAIL'}",
        f"- Result Dir: {path.resolve()}",
        f"- Raw JSON: {raw_json.resolve()}",
        f"- Run Log: {run_log.resolve()}",
        "",
        "## 场景 A: 1000 批次 × 100 个 1KB 对象",
        "",
        "| Key | Value |",
        "|---|---:|",
    ]
    sa = result.get("scenario_a", {})
    lines.append(f"| `elapsed_ms` | {sa.get('elapsed_ms', 'N/A')} |")
    lines.append(f"| `ops_ok` | {sa.get('ops_ok', 'N/A')} |")
    lines.append(f"| `ops_fail` | {sa.get('ops_fail', 'N/A')} |")
    lines.append(f"| `threshold` | <= 200ms |")
    lines.append(f"| `passed` | {result.get('passed_a', 'N/A')} |")

    lines.extend([
        "",
        "## 场景 B: 100 批次 × 1000 个 1KB 对象",
        "",
        "| Key | Value |",
        "|---|---:|",
    ])
    sb = result.get("scenario_b", {})
    lines.append(f"| `elapsed_ms` | {sb.get('elapsed_ms', 'N/A')} |")
    lines.append(f"| `ops_ok` | {sb.get('ops_ok', 'N/A')} |")
    lines.append(f"| `ops_fail` | {sb.get('ops_fail', 'N/A')} |")
    lines.append(f"| `threshold` | <= 100ms |")
    lines.append(f"| `passed` | {result.get('passed_b', 'N/A')} |")

    lines.extend([
        "",
        "## 统计口径",
        "",
        "- 使用 nr_bench --count 模式，精确执行指定数量的串行 RPC_KV_PUT_BATCH 调用。",
        "- 场景 A：1000 次 batch 调用，每次 100 个 1KB 对象。",
        "- 场景 B：100 次 batch 调用，每次 1000 个 1KB 对象。",
        "- 计时从第一批提交到最后一批响应返回。",
        "- 不统计构建、脚本启动、环境启动和 warmup 时间。",
    ])
    note = result.get("note")
    if note:
        lines.extend(["", "## 说明", "", str(note)])
    (path / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    root = repo_root()
    path = out_dir()
    logs = log_dir()
    bin_path = resolve_cmake_bin(root, "nr_bench")
    uds = os.environ.get("UDS", "/tmp/native_rdma-dp.sock")
    raw_json = path / "raw.json"
    run_log = logs / "run.log"

    if not os.access(bin_path, os.X_OK):
        result = {"metric": "perf_04", "passed": False, "error": f"nr_bench missing: {bin_path}"}
        write_json(raw_json, result)
        run_log.write_text(result["error"] + "\n", encoding="utf-8")
        write_summary(path, result, run_log, raw_json)
        return 2
    if not can_connect_uds(uds):
        result = {"metric": "perf_04", "passed": False, "error": f"data plane UDS is not connectable: {uds}; this test requires the data plane."}
        write_json(raw_json, result)
        run_log.write_text(result["error"] + "\n", encoding="utf-8")
        write_summary(path, result, run_log, raw_json)
        return 2

    run_lines: list[str] = []
    keyspace = "1000"

    # Warmup
    warmup_cmd = [
        str(bin_path), f"--uds={uds}", "--op=put",
        "--batch=100", "--count=20", "--val-size=1024", f"--keyspace={keyspace}",
    ]
    proc = subprocess.run(warmup_cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    run_lines.append(f"[warmup] $ {' '.join(warmup_cmd)}\nexit={proc.returncode}\n{proc.stdout}\n")

    # Scenario A: 1000 batches × 100 objects
    cmd_a = [
        str(bin_path), f"--uds={uds}", "--op=put",
        "--batch=100", "--count=1000", "--val-size=1024", f"--keyspace={keyspace}",
    ]
    proc = subprocess.run(cmd_a, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    run_lines.append(f"[scenario-A] $ {' '.join(cmd_a)}\nexit={proc.returncode}\n{proc.stdout}\n")
    sa = parse_bench_output(proc.stdout)

    # Scenario B: 100 batches × 1000 objects
    cmd_b = [
        str(bin_path), f"--uds={uds}", "--op=put",
        "--batch=1000", "--count=100", "--val-size=1024", f"--keyspace={keyspace}",
    ]
    proc = subprocess.run(cmd_b, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    run_lines.append(f"[scenario-B] $ {' '.join(cmd_b)}\nexit={proc.returncode}\n{proc.stdout}\n")
    sb = parse_bench_output(proc.stdout)

    ms_a = sa.get("elapsed_ms", 1e9)
    ms_b = sb.get("elapsed_ms", 1e9)
    fail_a = sa.get("ops_fail", -1)
    fail_b = sb.get("ops_fail", -1)
    passed_a = ms_a <= 200.0 and fail_a == 0
    passed_b = ms_b <= 100.0 and fail_b == 0

    result = {
        "metric": "perf_04_batch_latency",
        "scenario_a": sa,
        "scenario_b": sb,
        "passed_a": bool(passed_a),
        "passed_b": bool(passed_b),
        "passed": bool(passed_a and passed_b),
    }

    ts = time.strftime("%Y%m%d_%H%M%S")
    write_json(logs / f"perf_04_batch_latency_{ts}.json", result)
    write_json(raw_json, result)
    run_log.write_text("\n".join(run_lines), encoding="utf-8")
    write_summary(path, result, run_log, raw_json)
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
