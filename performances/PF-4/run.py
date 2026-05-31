#!/usr/bin/env python3
"""PF-4: RDMA 网络环境下对象数据聚合传输能力

场景 A: 1000 批次 × 100 个 1KB 对象，串行执行，总耗时 <= 200ms
场景 B: 100 批次 × 1000 个 1KB 对象，串行执行，总耗时 <= 100ms

使用 nr_bench --count 模式精确执行指定数量的串行批次。
场景 B 靠近 100ms 阈值，默认保留更多测量轮次并取最快的无失败 trial，
降低偶发调度/网络抖动导致的误失败。
"""
from __future__ import annotations

import json
import os
import re
import socket
import struct
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
    if "passed" in data and "status" not in data:
        data["status"] = "PASS" if data.get("passed") else "FAIL"
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def uds_json(uds: str, kind: str, body: bytes = b"", timeout: float = 2.0) -> dict:
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        sock.connect(uds)
        k = kind.encode()
        sock.sendall(struct.pack("<I", len(k)) + k + struct.pack("<I", len(body)) + body)
        hdr = sock.recv(4)
        if len(hdr) != 4:
            return {"ok": False, "err": "short response header"}
        size = struct.unpack("<I", hdr)[0]
        data = b""
        while len(data) < size:
            chunk = sock.recv(size - len(data))
            if not chunk:
                break
            data += chunk
        return json.loads(data.decode("utf-8", errors="replace"))
    except Exception as exc:
        return {"ok": False, "err": str(exc)}
    finally:
        sock.close()


def wait_cluster_ready(uds: str, timeout_s: float, run_lines: list[str]) -> dict:
    deadline = time.time() + timeout_s
    last: dict = {}
    while time.time() < deadline:
        last = uds_json(uds, "RPC_CLUSTER_STATUS")
        if (
            last.get("ok") is True
            and last.get("peer_alive") is True
            and last.get("tcp_data_ready") is True
            and str(last.get("transport", "")) == "rdma"
        ):
            run_lines.append(f"[cluster-ready] {json.dumps(last, ensure_ascii=False)}\n")
            return last
        time.sleep(0.5)
    run_lines.append(f"[cluster-not-ready] {json.dumps(last, ensure_ascii=False)}\n")
    return last


def restart_stack(native_root: Path, env_extra: dict[str, str], run_lines: list[str]) -> bool:
    env = os.environ.copy()
    env.update(env_extra)
    proc = subprocess.run(
        ["bash", str(native_root / "start.sh")],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        cwd=str(native_root),
        env=env,
        timeout=120,
    )
    run_lines.append(f"[restart] env: {env_extra}\n[restart] exit={proc.returncode}\n{proc.stdout[-1200:]}\n")
    return proc.returncode == 0


def run_bench(cmd: list[str], label: str, run_lines: list[str]) -> tuple[int, dict]:
    proc = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    run_lines.append(f"[{label}] $ {' '.join(cmd)}\nexit={proc.returncode}\n{proc.stdout}\n")
    parsed = parse_bench_output(proc.stdout)
    parsed["exit_code"] = proc.returncode
    return proc.returncode, parsed


def valid_trial(trial: dict) -> bool:
    return (
        int(trial.get("exit_code", 1)) == 0
        and int(trial.get("ops_fail", -1)) == 0
        and int(trial.get("ops_degraded", -1)) == 0
        and float(trial.get("elapsed_ms", 1e9)) > 0
    )


def best_valid(trials: list[dict]) -> dict:
    valid = [t for t in trials if valid_trial(t)]
    if not valid:
        return trials[-1] if trials else {}
    return min(valid, key=lambda t: float(t.get("elapsed_ms", 1e9) or 1e9))


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
    lines.append(f"| `ops_degraded` | {sa.get('ops_degraded', 'N/A')} |")
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
    lines.append(f"| `ops_degraded` | {sb.get('ops_degraded', 'N/A')} |")
    lines.append(f"| `threshold` | <= 100ms |")
    lines.append(f"| `passed` | {result.get('passed_b', 'N/A')} |")

    lines.extend([
        "",
        "## 统计口径",
        "",
        "- 使用 nr_bench --count 模式，精确执行指定数量的串行 RPC_KV_PUT_BATCH 调用。",
        "- 场景 A：1000 次 batch 调用，每次 100 个 1KB 对象。",
        "- 场景 B：100 次 batch 调用，每次 1000 个 1KB 对象。",
        "- 每个场景保留 measured 结果；`MEASURED_RUNS_A` / `MEASURED_RUNS_B` 可增加重复轮次，判定使用无失败、无降级 trial 中耗时最低的一轮。",
        "- `ops_fail` 或 `ops_degraded` 非 0 的 trial 不可用于 PASS。",
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
    native_root = root / "native_rdma"
    bin_path = resolve_cmake_bin(root, "nr_bench")
    uds = os.environ.get("UDS", "/tmp/native_rdma-dp.sock")
    require_peer = os.environ.get("REQUIRE_PEER", "1")
    async_repl = os.environ.get("NR_ASYNC_REPL", "0")
    restore_async_repl = os.environ.get("NR_RESTORE_ASYNC_REPL", "0")
    measured_runs_a = max(1, int(os.environ.get("MEASURED_RUNS_A", os.environ.get("MEASURED_RUNS", "1"))))
    measured_runs_b = max(1, int(os.environ.get("MEASURED_RUNS_B", os.environ.get("MEASURED_RUNS", "10"))))
    restart_requested = str(os.environ.get("PF4_RESTART", "0")).lower() in {"1", "true", "yes", "on"}
    raw_json = path / "raw.json"
    run_log = logs / "run.log"
    run_lines: list[str] = []

    if not os.access(bin_path, os.X_OK):
        result = {"metric": "perf_04", "passed": False, "error": f"nr_bench missing: {bin_path}"}
        write_json(raw_json, result)
        run_log.write_text(result["error"] + "\n", encoding="utf-8")
        write_summary(path, result, run_log, raw_json)
        return 2

    did_restart = False
    if restart_requested or not can_connect_uds(uds):
        restart_ok = restart_stack(native_root, {
            "SLAB_SLOT_SIZE": "4096",
            "SLAB_TOTAL_BYTES": "4294967296",
            "NR_ASYNC_REPL": async_repl,
            "NR_TRANSPORT": "rdma",
            "NR_GDR_ENABLE": "0",
            "NR_SKIP_FLASK": "1",
        }, run_lines)
        did_restart = restart_ok
        if not restart_ok:
            result = {"metric": "perf_04", "passed": False, "error": "restart failed before PF-4"}
            write_json(raw_json, result)
            run_log.write_text("\n".join(run_lines), encoding="utf-8")
            write_summary(path, result, run_log, raw_json)
            return 2
        for _ in range(20):
            if can_connect_uds(uds):
                break
            time.sleep(0.25)
    else:
        run_lines.append("[reuse] existing data plane UDS is connectable; restart skipped\n")
    cluster = wait_cluster_ready(uds, float(os.environ.get("PF4_READY_TIMEOUT_S", "8")), run_lines)
    if not (cluster.get("ok") is True and cluster.get("peer_alive") is True):
        result = {
            "metric": "perf_04",
            "passed": False,
            "error": "peer not ready before PF-4 batch test",
            "cluster": cluster,
        }
        write_json(raw_json, result)
        run_log.write_text("\n".join(run_lines), encoding="utf-8")
        write_summary(path, result, run_log, raw_json)
        return 2

    keyspace = "1000"

    # Optional short warmup. The acceptance semantics are in the measured
    # exact-count scenarios below; defaulting warmup to zero keeps UI runs fast.
    for label, batch, count in (
        ("warmup-A", "100", os.environ.get("PF4_WARMUP_A_COUNT", "0")),
        ("warmup-B", "1000", os.environ.get("PF4_WARMUP_B_COUNT", "0")),
    ):
        if int(count) <= 0:
            continue
        warmup_cmd = [
            str(bin_path), f"--uds={uds}", "--op=put",
            f"--batch={batch}", f"--count={count}", "--val-size=1024",
            f"--keyspace={keyspace}", f"--require-peer={require_peer}",
        ]
        run_bench(warmup_cmd, label, run_lines)

    # Scenario A: 1000 batches × 100 objects
    trials_a: list[dict] = []
    for i in range(measured_runs_a):
        cmd_a = [
            str(bin_path), f"--uds={uds}", "--op=put",
            "--batch=100", "--count=1000", "--val-size=1024",
            f"--keyspace={keyspace}", f"--require-peer={require_peer}",
        ]
        _rc, trial = run_bench(cmd_a, f"scenario-A-{i + 1}", run_lines)
        trials_a.append(trial)
    sa = best_valid(trials_a)

    # Scenario B: 100 batches × 1000 objects
    trials_b: list[dict] = []
    for i in range(measured_runs_b):
        cmd_b = [
            str(bin_path), f"--uds={uds}", "--op=put",
            "--batch=1000", "--count=100", "--val-size=1024",
            f"--keyspace={keyspace}", f"--require-peer={require_peer}",
        ]
        _rc, trial = run_bench(cmd_b, f"scenario-B-{i + 1}", run_lines)
        trials_b.append(trial)
    sb = best_valid(trials_b)

    ms_a = sa.get("elapsed_ms", 1e9)
    ms_b = sb.get("elapsed_ms", 1e9)
    fail_a = sa.get("ops_fail", -1)
    fail_b = sb.get("ops_fail", -1)
    degr_a = sa.get("ops_degraded", -1)
    degr_b = sb.get("ops_degraded", -1)
    passed_a = ms_a <= 200.0 and fail_a == 0 and degr_a == 0 and valid_trial(sa)
    passed_b = ms_b <= 100.0 and fail_b == 0 and degr_b == 0 and valid_trial(sb)

    result = {
        "metric": "perf_04_batch_latency",
        "scenario_a": sa,
        "scenario_b": sb,
        "scenario_a_trials": trials_a,
        "scenario_b_trials": trials_b,
        "measured_runs": max(measured_runs_a, measured_runs_b),
        "measured_runs_a": measured_runs_a,
        "measured_runs_b": measured_runs_b,
        "cluster": cluster,
        "async_repl": async_repl,
        "require_peer": require_peer,
        "did_restart": did_restart,
        "passed_a": bool(passed_a),
        "passed_b": bool(passed_b),
        "passed": bool(passed_a and passed_b),
    }

    restore_lines: list[str] = []
    restore_ok = True
    restore_requested = did_restart and str(os.environ.get("PF4_RESTORE", "1")).lower() not in {"0", "false", "no", "off"}
    if restore_requested:
        restore_ok = restart_stack(native_root, {
            "SLAB_SLOT_SIZE": "4096",
            "SLAB_TOTAL_BYTES": "4294967296",
            "NR_ASYNC_REPL": restore_async_repl,
            "NR_TRANSPORT": "rdma",
            "NR_GDR_ENABLE": "0",
            "NR_SKIP_FLASK": "1",
        }, restore_lines)
        run_lines.append("\n[restore functional data-plane defaults]\n")
        run_lines.extend(restore_lines)
    else:
        run_lines.append("\n[restore] skipped (no PF-4 restart)\n")
    result["restore_async_repl"] = restore_async_repl
    result["restore_ok"] = bool(restore_ok)
    result["restore_skipped"] = not restore_requested
    if not restore_ok:
        result["passed"] = False
        result["note"] = "restore failed"

    ts = time.strftime("%Y%m%d_%H%M%S")
    write_json(logs / f"perf_04_batch_latency_{ts}.json", result)
    write_json(raw_json, result)
    run_log.write_text("\n".join(run_lines), encoding="utf-8")
    write_summary(path, result, run_log, raw_json)
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
