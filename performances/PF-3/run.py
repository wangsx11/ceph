#!/usr/bin/env python3
"""PF-3: RDMA 网络环境下 QoS 事件优先级传输能力

Threshold: gain_pct = (hi_ops - lo_ops) / lo_ops * 100% >= 22%

The QoS scheduler uses a token-bucket rate limiter on low-priority traffic.
The test restarts the data plane with NR_LO_RATE_KOPS tuned so the rate
limiter actively constrains low-priority, giving high-priority a measurable
throughput advantage.
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
from common import resolve_cmake_bin


PF_ID = "PF-3"
PF_NAME = "RDMA 网络环境下 QoS 事件优先级传输能力"
SOURCE_NO = 3
THRESHOLD = "高优先级相对低优先级处理效率提升 >= 22%"
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
        f"- Key Result: hi={result.get('hi_ops', 'N/A')} ops/s, lo={result.get('lo_ops', 'N/A')} ops/s, gain={result.get('gain_pct', 'N/A')}%",
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
    for key in ("hi_ops", "lo_ops", "gain_pct", "threshold_gain_pct",
                "hi_fail", "lo_fail", "hi_degraded", "lo_degraded",
                "hi_p99_us", "lo_p99_us", "lo_rate_limit_kops"):
        lines.append(f"| `{key}` | {result.get(key, 'N/A')} |")
    lines.extend([
        "",
        "## 统计口径",
        "",
        "- `gain_pct = (hi_ops - lo_ops) / lo_ops * 100%`。",
        "- 高、低优先级并发压测，分别统计 measured 窗口内完成效率。",
        "- QoS 通过 token-bucket 限速器约束低优先级吞吐，高优先级不限速。",
        "- 不统计构建、脚本启动、环境启动和 warmup 时间。",
    ])
    note = result.get("error") or result.get("note")
    if note:
        lines.extend(["", "## 说明", "", str(note)])
    (path / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def fail_early(path: Path, message: str, code: int = 2) -> int:
    logs = log_dir()
    result = {"metric": "perf_03_qos", "passed": False, "error": message}
    raw_json = path / "raw.json"
    run_log = logs / "run.log"
    write_json(raw_json, result)
    run_log.write_text(message + "\n", encoding="utf-8")
    write_summary(path, result, run_log, raw_json)
    return code


def restart_stack(native_root: Path, env_extra: dict, run_lines: list[str]) -> bool:
    env = os.environ.copy()
    env.update(env_extra)
    start_sh = native_root / "start.sh"
    run_lines.append(f"[restart] env: {env_extra}\n")
    proc = subprocess.run(
        ["bash", str(start_sh)],
        text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        cwd=str(native_root), env=env, timeout=120,
    )
    run_lines.append(f"[restart] exit={proc.returncode}\n{proc.stdout[-500:]}\n")
    return proc.returncode == 0


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
    async_repl = os.environ.get("NR_ASYNC_REPL", "1")
    lo_rate_kops = os.environ.get("NR_LO_RATE_KOPS", "200")
    raw_json = path / "raw.json"
    run_log = logs / "run.log"

    if not os.access(bin_path, os.X_OK):
        return fail_early(path, f"nr_bench missing: {bin_path}")

    run_lines: list[str] = []

    # Restart data plane with tuned lo-priority rate limit
    restart_ok = restart_stack(native_root, {
        "NR_ASYNC_REPL": async_repl,
        "NR_LO_RATE_KOPS": lo_rate_kops,
    }, run_lines)

    if not restart_ok:
        run_log.write_text("\n".join(run_lines), encoding="utf-8")
        return fail_early(path, "Failed to restart data plane")

    for _ in range(30):
        if Path(uds).is_socket():
            break
        time.sleep(0.5)
    time.sleep(3)  # heartbeat stabilization

    if not Path(uds).is_socket():
        run_log.write_text("\n".join(run_lines), encoding="utf-8")
        return fail_early(path, f"data plane not running (no {uds})")

    # Warmup (not measured): stabilize connections and slab
    warmup_cmd = [
        str(bin_path), f"--uds={uds}", "--op=put", "--prio=hi",
        f"--threads={threads}", "--val-size=1024", "--duration=3",
        "--keyspace=5000",
    ]
    proc = subprocess.run(warmup_cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    run_lines.append(f"[warmup] $ {' '.join(warmup_cmd)}\nexit={proc.returncode}\n{proc.stdout}\n")

    # Measured: run hi and lo concurrently
    cmd_hi = [
        str(bin_path), f"--uds={uds}", "--op=put", "--prio=hi",
        f"--threads={threads}", "--val-size=1024", f"--duration={dur}",
        "--keyspace=5000", f"--require-peer={require_peer}",
    ]
    cmd_lo = [
        str(bin_path), f"--uds={uds}", "--op=put", "--prio=lo",
        f"--threads={threads}", "--val-size=1024", f"--duration={dur}",
        "--keyspace=5000", f"--require-peer={require_peer}",
    ]
    p_hi = subprocess.Popen(cmd_hi, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    p_lo = subprocess.Popen(cmd_lo, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    out_hi, _ = p_hi.communicate()
    out_lo, _ = p_lo.communicate()
    run_lines.append(
        f"[measured-hi] $ {' '.join(cmd_hi)}\nexit={p_hi.returncode}\n{out_hi}\n\n"
        f"[measured-lo] $ {' '.join(cmd_lo)}\nexit={p_lo.returncode}\n{out_lo}\n"
    )

    hi = parse_bench_output(out_hi or "")
    lo = parse_bench_output(out_lo or "")
    hi_ops = float(hi.get("ops_per_sec", 0))
    lo_ops = float(lo.get("ops_per_sec", 0))
    gain_pct = ((hi_ops - lo_ops) / lo_ops * 100.0) if lo_ops > 0 else 0.0
    hi_fail = int(hi.get("ops_fail", 0))
    lo_fail = int(lo.get("ops_fail", 0))
    hi_degr = int(hi.get("ops_degraded", 0))
    lo_degr = int(lo.get("ops_degraded", 0))

    hi_ok = int(hi.get("ops_ok", 0))
    lo_ok = int(lo.get("ops_ok", 0))
    hi_total = hi_ok + hi_fail
    lo_total = lo_ok + lo_fail
    hi_fail_pct = (hi_fail / hi_total * 100.0) if hi_total > 0 else 0.0
    lo_fail_pct = (lo_fail / lo_total * 100.0) if lo_total > 0 else 0.0
    passed = bool(
        gain_pct >= 22.0
        and hi_fail_pct < 10.0
        and lo_fail_pct < 10.0
        and hi_degr == 0
        and lo_degr == 0
    )

    result = {
        "metric": "perf_03_qos",
        "hi_ops": hi_ops,
        "lo_ops": lo_ops,
        "gain_pct": round(gain_pct, 2),
        "threshold_gain_pct": 22.0,
        "hi_fail": hi_fail,
        "lo_fail": lo_fail,
        "hi_degraded": hi_degr,
        "lo_degraded": lo_degr,
        "hi_p99_us": hi.get("lat_p99_us", 0),
        "lo_p99_us": lo.get("lat_p99_us", 0),
        "lo_rate_limit_kops": int(lo_rate_kops),
        "passed": passed,
        "raw_hi": hi,
        "raw_lo": lo,
    }

    ts = time.strftime("%Y%m%d_%H%M%S")
    write_json(logs / f"perf_03_qos_{ts}.json", result)
    write_json(raw_json, result)
    run_log.write_text("\n".join(run_lines), encoding="utf-8")
    write_summary(path, result, run_log, raw_json)
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
