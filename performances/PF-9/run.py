#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import ensure_cmake_target, resolve_cmake_bin


PF_ID = "PF-9"
PF_NAME = "仿真引擎内存池化能力"
SOURCE_NO = 9
THRESHOLD = "性能损失 <= 5%；内存节省 >= 7%；分配/释放吞吐提升 >= 20%"


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


def write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def write_summary(path: Path, result: dict, run_log: Path, raw_json: Path) -> None:
    lines = [
        f"# {PF_ID} Summary",
        "",
        f"- Metric: {PF_NAME}",
        f"- Source: `docs/性能要求.md` 第 {SOURCE_NO} 条",
        f"- Generated At: {time.strftime('%Y-%m-%dT%H:%M:%S%z')}",
        f"- Key Result: overhead={result.get('overhead_pct', 'N/A')}%, savings={result.get('savings_pct', 'N/A')}%, scale={result.get('scale_gain_pct', 'N/A')}%",
        f"- Threshold: {THRESHOLD}",
        f"- Result: {'PASS' if result.get('passed') else 'FAIL'}",
        f"- Result Dir: {path.resolve()}",
        f"- Raw JSON: {raw_json.resolve()}",
        "- Raw CSV: 未生成",
        f"- Run Log: {run_log.resolve()}",
        "",
        "## 关键统计值",
        "",
        "| Key | Value |",
        "|---|---:|",
    ]
    for key in ("overhead_pct", "savings_pct", "scale_gain_pct", "threads_multi", "malloc_ops_1t", "slab_ops_1t", "malloc_ops_Nt", "slab_ops_Nt", "passed_overhead", "passed_savings", "passed_scale"):
        lines.append(f"| `{key}` | {result.get(key, 'N/A')} |")
    lines.extend([
        "",
        "## 统计口径",
        "",
        "- 测试逻辑由 `native_rdma/tests/performance/perf_09_mempool.sh` 迁移到本 `run.py`。",
        "- 执行 `native_rdma/build/bin/nr_mempool_bench` 并直接记录其 JSON 输出。",
        "- 基线与内存池场景使用相同对象大小、线程数、操作数和硬件环境。",
    ])
    note = result.get("error") or result.get("note")
    if note:
        lines.extend(["", "## 说明", "", str(note)])
    (path / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def fail(path: Path, message: str, code: int = 2) -> int:
    logs = log_dir()
    result = {"metric": "perf_09_mempool", "passed": False, "error": message}
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
    bin_path = resolve_cmake_bin(root, "nr_mempool_bench")
    threads = os.environ.get("THREADS", "8")
    raw_json = path / "raw.json"
    run_log = logs / "run.log"

    if not os.access(bin_path, os.X_OK):
        return fail(path, f"nr_mempool_bench missing: {bin_path} (run: cmake --build build -j)")

    cmd = [str(bin_path), f"--threads={threads}"]
    proc = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    run_log.write_text(f"$ {' '.join(cmd)}\nexit={proc.returncode}\n{proc.stdout}\n", encoding="utf-8")
    try:
        result = json.loads(proc.stdout)
    except Exception as exc:
        if "GLIBC_" in proc.stdout or "not found" in proc.stdout:
            try:
                bin_path = ensure_cmake_target(root, "nr_mempool_bench")
                cmd = [str(bin_path), f"--threads={threads}"]
                proc = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
                run_log.write_text(f"$ {' '.join(cmd)}\nexit={proc.returncode}\n{proc.stdout}\n", encoding="utf-8")
                result = json.loads(proc.stdout)
            except Exception as rebuild_exc:
                return fail(path, f"failed after rebuilding nr_mempool_bench: {rebuild_exc}\n{proc.stdout[-2000:]}")
        else:
            return fail(path, f"failed to parse nr_mempool_bench JSON: {exc}\n{proc.stdout[-2000:]}")
    if proc.returncode != 0:
        result["note"] = f"nr_mempool_bench exited with {proc.returncode}"
        result["passed"] = False

    ts = time.strftime("%Y%m%d_%H%M%S")
    write_json(logs / f"perf_09_mempool_{ts}.json", result)
    write_json(raw_json, result)
    write_summary(path, result, run_log, raw_json)
    return 0 if result.get("passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
