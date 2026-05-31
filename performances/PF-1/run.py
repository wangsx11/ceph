#!/usr/bin/env python3
"""PF-1: RDMA 网络环境分布式通讯能力

Two sub-tests verified independently (分项验收):
  A) 1KB 小对象吞吐 >= 1,000,000 ops/s
  B) 大对象带宽利用率 >= 50%  (on 100 Gbps link)

Sub-test A uses the current running data plane (SLAB_SLOT_SIZE=4096).
Sub-test B restarts both nodes with SLAB_SLOT_SIZE=1048576 (1MB) so large
objects can be accepted, then restores the original config afterward.

Pass when BOTH sub-tests pass.
"""
from __future__ import annotations

import json
import mmap
import os
import re
import subprocess
import sys
import time
import struct
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import resolve_cmake_bin


PF_ID = "PF-1"
PF_NAME = "RDMA 网络环境分布式通讯能力"
SOURCE_NO = 1
THRESHOLD_OPS = "1KB 对象吞吐量 >= 1,000,000 ops/s"
THRESHOLD_UTIL = "大对象带宽利用率 >= 50%"
NUM = r"[-+]?\d+(?:\.\d+)?"
METRICS_FMT = "<Q Q Q Q d d d d d Q Q Q d"
METRICS_KEYS = [
    "ts_ns", "ops_total", "ops_hi", "ops_lo",
    "bw_tx_gbps", "bw_rx_gbps", "rdma_util_pct",
    "lat_avg_us", "lat_p99_us",
    "obj_dram", "obj_nvme", "obj_hdd", "replica_lag_us",
]
METRICS_SIZE = struct.calcsize(METRICS_FMT)


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
    patterns = {
        "elapsed_s": rf"elapsed\s*:\s*({NUM})",
        "ops_per_sec": rf"ops/s\s*:\s*({NUM})",
        "val_size": r"val_size=(\d+)",
    }
    for key, pat in patterns.items():
        m = re.search(pat, text)
        if m:
            out[key] = float(m.group(1)) if key != "val_size" else int(m.group(1))
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
    m = re.search(rf"latency us\s*:\s*avg=({NUM})\s+p50=({NUM})(?:\s+p90=({NUM}))?\s+p99=({NUM})\s+p99\.9=({NUM})\s+max=({NUM})", text)
    if m:
        out["lat_avg_us"] = float(m.group(1))
        out["lat_p50_us"] = float(m.group(2))
        out["lat_p99_us"] = float(m.group(4))
        out["lat_p99_9_us"] = float(m.group(5))
        out["lat_max_us"] = float(m.group(6))
    # Byte-based bandwidth counters
    m = re.search(rf"req_bytes\s*:\s*(\d+)\s*\(({NUM})\s*MB/s\)", text)
    if m:
        out["req_bytes"] = int(m.group(1))
        out["req_mbps"] = float(m.group(2))
    m = re.search(rf"resp_bytes\s*:\s*(\d+)\s*\(({NUM})\s*MB/s\)", text)
    if m:
        out["resp_bytes"] = int(m.group(1))
        out["resp_mbps"] = float(m.group(2))
    return out


def read_metrics_shm(path: str) -> dict:
    try:
        with open(path, "rb") as f:
            mm = mmap.mmap(f.fileno(), METRICS_SIZE, prot=mmap.PROT_READ)
            raw = mm.read(METRICS_SIZE)
            mm.close()
        if len(raw) != METRICS_SIZE:
            return {}
        return dict(zip(METRICS_KEYS, struct.unpack(METRICS_FMT, raw)))
    except Exception:
        return {}


def run_with_network_samples(cmd: list[str], metrics_shm: str, sample_interval_s: float = 0.2) -> tuple[int, str, dict]:
    proc = subprocess.Popen(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    samples: list[dict] = []
    seen_ts: set[int] = set()
    # The data-plane metrics thread publishes windowed RDMA tx bandwidth in
    # bw_tx_gbps and resets its byte counter every update. Sampling the shm
    # during the measured nr_bench run gives the actual RDMA network transmit
    # rate, not the client->UDS request byte rate.
    while proc.poll() is None:
        m = read_metrics_shm(metrics_shm)
        ts = int(m.get("ts_ns", 0) or 0)
        tx = float(m.get("bw_tx_gbps", 0.0) or 0.0)
        if ts > 0 and ts not in seen_ts:
            seen_ts.add(ts)
            samples.append({"ts_ns": ts, "bw_tx_gbps": tx})
        time.sleep(sample_interval_s)
    stdout, _ = proc.communicate()
    m = read_metrics_shm(metrics_shm)
    ts = int(m.get("ts_ns", 0) or 0)
    tx = float(m.get("bw_tx_gbps", 0.0) or 0.0)
    if ts > 0 and ts not in seen_ts:
        samples.append({"ts_ns": ts, "bw_tx_gbps": tx})
    positive = [float(s["bw_tx_gbps"]) for s in samples if float(s.get("bw_tx_gbps", 0.0)) > 0.0]
    if positive:
        avg = sum(positive) / len(positive)
        peak = max(positive)
    else:
        avg = 0.0
        peak = 0.0
    return proc.returncode or 0, stdout or "", {
        "samples": samples,
        "positive_samples": len(positive),
        "network_tx_gbps_avg": avg,
        "network_tx_gbps_peak": peak,
    }


def write_json(path: Path, data: dict) -> None:
    if "passed" in data and "status" not in data:
        data["status"] = "PASS" if data.get("passed") else "FAIL"
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def write_summary(path: Path, result: dict, run_log: Path, raw_json: Path) -> None:
    passed = bool(result.get("passed"))
    note = result.get("error") or result.get("note") or ""
    lines = [
        f"# {PF_ID} Summary",
        "",
        f"- Metric: {PF_NAME}",
        f"- Source: `docs/性能要求.md` 第 {SOURCE_NO} 条",
        f"- Generated At: {time.strftime('%Y-%m-%dT%H:%M:%S%z')}",
        f"- Threshold (A): {THRESHOLD_OPS}",
        f"- Threshold (B): {THRESHOLD_UTIL}（按 RDMA 网络发送带宽计算）",
        f"- Result: {'PASS' if passed else 'FAIL'}",
        f"- Result Dir: {path.resolve()}",
        f"- Raw JSON: {raw_json.resolve()}",
        f"- Run Log: {run_log.resolve()}",
        "",
        "## Sub-test A: 1KB 小对象吞吐",
        "",
        "| Key | Value |",
        "|---|---:|",
    ]
    for key in ("ops_threads", "ops_val_size", "ops_per_sec", "ops_fail", "ops_degraded", "passed_ops"):
        lines.append(f"| `{key}` | {result.get(key, 'N/A')} |")
    lines.append(f"| `ops_success_rate_pct` | {result.get('ops_success_rate_pct', 'N/A')}% |")
    lines.append(f"| `ops_fail_pct` | {result.get('ops_fail_pct', 'N/A')}% |")
    lines.extend([
        "",
        "## Sub-test B: 大对象带宽利用率",
        "",
        f"- Network Bandwidth Utilization: {result.get('bw_util_pct', 'N/A')}% / threshold {result.get('thresholds', {}).get('util_pct', 50.0)}%",
        f"- Network TX Bandwidth: avg={result.get('bw_network_tx_gbps_avg', 'N/A')} Gbps, peak={result.get('bw_network_tx_gbps_peak', 'N/A')} Gbps",
        f"- Success Rate: {result.get('bw_success_rate_pct', 'N/A')}%",
        "",
        "| Key | Value |",
        "|---|---:|",
    ])
    for key in ("bw_threads", "bw_val_size", "bw_network_tx_gbps_avg", "bw_network_tx_gbps_peak", "bw_link_gbps", "bw_util_pct", "bw_fail", "bw_degraded", "passed_util"):
        lines.append(f"| `{key}` | {result.get(key, 'N/A')} |")
    lines.append(f"| `bw_success_rate_pct` | {result.get('bw_success_rate_pct', 'N/A')}% |")
    lines.append(f"| `bw_fail_pct` | {result.get('bw_fail_pct', 'N/A')}% |")
    trials = result.get("bw_trials") or []
    if trials:
        lines.extend([
            "",
            "### 大对象线程扫描",
            "",
            "| Threads | Network Utilization | Network TX Avg Gbps | Network TX Peak Gbps | Client Req Gbps | Success Rate | Fail Count | Fail Rate | Result |",
            "|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ])
        for trial in trials:
            ok = int(trial.get("ops_ok", 0))
            fail = int(trial.get("ops_fail", 0))
            total = ok + fail
            success = (ok / total * 100.0) if total else 0.0
            lines.append(
                f"| {trial.get('threads', 'N/A')} | {trial.get('util_pct', 'N/A')}% | "
                f"{trial.get('network_tx_gbps_avg', 'N/A')} | "
                f"{trial.get('network_tx_gbps_peak', 'N/A')} | "
                f"{trial.get('client_req_gbps', 'N/A')} | {success:.3f}% | "
                f"{fail} | {trial.get('fail_pct', 'N/A')}% | "
                f"{'PASS' if trial.get('passed') else 'FAIL'} |"
            )
    lines.extend([
        "",
        "## 统计口径",
        "",
        "- 1KB 小对象吞吐和大对象带宽利用率分项验收，两项均通过则 PASS。",
        "- 两个子项都要求失败数为 0；任何 `ops_fail` 都不计入通过结果。",
        "- 小对象测试使用 batch PUT 模式，计算 ops_per_sec。",
        "- 大对象测试使用 1MB 对象，带宽利用率基于数据面 shared-memory metrics 的 `bw_tx_gbps` 计算，即 RDMA 网络发送带宽。",
        "- `req_bytes` 只作为客户端请求字节辅助数据，不用于网络带宽利用率判定。",
        "- 不统计构建、脚本启动、环境启动和 warmup 时间。",
    ])
    if note:
        lines.extend(["", "## 说明", "", str(note)])
    (path / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def fail(path: Path, message: str, code: int = 2) -> int:
    result = {"metric": "perf_01", "passed": False, "error": message}
    logs = log_dir()
    raw_json = path / "raw.json"
    run_log = logs / "run.log"
    write_json(raw_json, result)
    run_log.write_text(message + "\n", encoding="utf-8")
    write_summary(path, result, run_log, raw_json)
    return code


def restart_stack(native_root: Path, env_extra: dict, run_lines: list[str]) -> bool:
    """Stop and restart both data-plane nodes via start.sh with extra env vars."""
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
    native_root = root / "native_rdma"
    path = out_dir()
    logs = log_dir()
    raw_json = path / "raw.json"
    run_log = logs / "run.log"
    bin_path = resolve_cmake_bin(root, "nr_bench")
    uds = os.environ.get("UDS", "/tmp/native_rdma-dp.sock")
    dur = os.environ.get("DUR", "4")
    bw_dur = os.environ.get("BW_DUR", dur)
    ops_dur = os.environ.get("OPS_DUR", dur)
    link_gbps = float(os.environ.get("LINK_GBPS", "100"))
    require_peer = os.environ.get("REQUIRE_PEER", "1")
    async_repl = os.environ.get("NR_ASYNC_REPL", "1")
    restore_async_repl = os.environ.get("NR_RESTORE_ASYNC_REPL", "0")
    metrics_shm = os.environ.get("NR_METRICS_SHM", "/tmp/native_rdma-metrics.shm")

    if not os.access(bin_path, os.X_OK):
        return fail(path, f"nr_bench missing: {bin_path}")

    run_lines: list[str] = []
    # Note: UDS check is deferred since sub-test B restarts the data plane.

    # ================================================================
    # Sub-test B (first): 大对象带宽利用率 >= 50%
    # Run this first because it requires a restart with 1MB slab slots.
    # The final restart restores 4KB slots for sub-test A.
    # ================================================================
    run_lines.append("=" * 60 + "\nSub-test B: large-object bandwidth utilization\n" + "=" * 60 + "\n")

    bw_val_size = int(os.environ.get("BW_VAL_SIZE", "1048576"))  # 1MB
    bw_slab_total = os.environ.get("BW_SLAB_TOTAL", "4294967296")  # 4GB
    bw_threads_list = [
        int(x.strip())
        for x in os.environ.get("BW_THREADS_LIST", os.environ.get("BW_THREADS", "4")).split(",")
        if x.strip()
    ]
    if not bw_threads_list:
        bw_threads_list = [4]
    bw_threads = bw_threads_list[-1]
    bw_batch = os.environ.get("BW_BATCH", "1")
    bw_keyspace = os.environ.get("BW_KEYSPACE", "512")

    restart_ok = restart_stack(native_root, {
        "SLAB_SLOT_SIZE": str(bw_val_size),
        "SLAB_TOTAL_BYTES": bw_slab_total,
        "NR_ASYNC_REPL": async_repl,
    }, run_lines)

    passed_util = False
    bw_write_gbps = 0.0
    bw_util_pct = 0.0
    bw_network_tx_gbps_avg = 0.0
    bw_network_tx_gbps_peak = 0.0
    bw_fail = 0
    bw_degraded = 0
    bw_raw: dict = {}
    bw_trials: list[dict] = []

    if not restart_ok:
        run_lines.append("[ERROR] Failed to restart data plane with 1MB slots\n")
    else:
        for _ in range(30):
            if Path(uds).is_socket():
                break
            time.sleep(0.5)

        if not Path(uds).is_socket():
            run_lines.append("[ERROR] UDS not available after restart\n")
        else:
            # Warmup: let heartbeat stabilize and fill keyspace
            warmup_cmd = [
                str(bin_path), f"--uds={uds}", "--op=put",
                f"--threads={max(bw_threads_list)}", f"--val-size={bw_val_size}",
                f"--duration={os.environ.get('PF1_BW_WARMUP_DUR', '1')}",
                f"--keyspace={bw_keyspace}", "--shared-keyspace=1",
                f"--batch={bw_batch}",
            ]
            proc = subprocess.run(warmup_cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            run_lines.append(f"[warmup-bw] $ {' '.join(warmup_cmd)}\nexit={proc.returncode}\n{proc.stdout}\n")

            # Measured runs: sweep thread counts and accept only a zero-fail
            # result. If every trial has failures, keep the highest-utilization
            # trial for reporting and mark the sub-test FAIL.
            best_trial: dict | None = None
            best_passing_trial: dict | None = None
            for trial_threads in bw_threads_list:
                cmd = [
                    str(bin_path), f"--uds={uds}", "--op=put",
                    f"--threads={trial_threads}", f"--val-size={bw_val_size}",
                    f"--duration={bw_dur}", f"--keyspace={bw_keyspace}",
                    "--shared-keyspace=1", f"--require-peer={require_peer}",
                    f"--batch={bw_batch}",
                ]
                rc, stdout, net = run_with_network_samples(cmd, metrics_shm)
                run_lines.append(f"[measured-bw threads={trial_threads}] $ {' '.join(cmd)}\nexit={rc}\n{stdout}\nnetwork_samples={json.dumps(net, ensure_ascii=False)}\n")
                parsed = parse_bench_output(stdout)
                elapsed = float(parsed.get("elapsed_s", 1.0)) or 1.0
                req_bytes = int(parsed.get("req_bytes", 0))
                fail_count = int(parsed.get("ops_fail", 0))
                degraded_count = int(parsed.get("ops_degraded", 0))
                client_req_gbps = (req_bytes / elapsed) * 8 / 1e9
                network_avg_gbps = float(net.get("network_tx_gbps_avg", 0.0) or 0.0)
                network_peak_gbps = float(net.get("network_tx_gbps_peak", 0.0) or 0.0)
                util_pct = (network_avg_gbps / link_gbps * 100.0) if link_gbps > 0 else 0.0
                ok_count = int(parsed.get("ops_ok", 0))
                total_count = ok_count + fail_count
                fail_pct = (fail_count / total_count * 100.0) if total_count > 0 else 0.0
                trial = {
                    "threads": trial_threads,
                    "network_tx_gbps_avg": round(network_avg_gbps, 3),
                    "network_tx_gbps_peak": round(network_peak_gbps, 3),
                    "client_req_gbps": round(client_req_gbps, 3),
                    "util_pct": round(util_pct, 2),
                    "ops_ok": ok_count,
                    "ops_fail": fail_count,
                    "fail_pct": round(fail_pct, 3),
                    "ops_degraded": degraded_count,
                    "passed": bool(util_pct >= 50.0 and fail_count == 0 and degraded_count == 0),
                    "network_samples": net.get("samples", []),
                    "raw": parsed,
                }
                bw_trials.append(trial)
                if best_trial is None or util_pct > float(best_trial["util_pct"]):
                    best_trial = trial
                if trial["passed"] and (best_passing_trial is None or util_pct > float(best_passing_trial["util_pct"])):
                    best_passing_trial = trial

            selected = best_passing_trial or best_trial
            if selected:
                bw_threads = int(selected["threads"])
                bw_write_gbps = float(selected["client_req_gbps"])
                bw_network_tx_gbps_avg = float(selected["network_tx_gbps_avg"])
                bw_network_tx_gbps_peak = float(selected["network_tx_gbps_peak"])
                bw_util_pct = float(selected["util_pct"])
                bw_fail = int(selected["ops_fail"])
                bw_degraded = int(selected["ops_degraded"])
                bw_raw = selected["raw"]
                passed_util = bool(selected["passed"])

    # ================================================================
    # Sub-test A: 1KB 小对象吞吐 >= 1,000,000 ops/s
    # Restart with 4KB slots (fresh state for clean measurement)
    # ================================================================
    run_lines.append("\n" + "=" * 60 + "\nSub-test A: 1KB ops throughput\n" + "=" * 60 + "\n")

    restart_stack(native_root, {
        "SLAB_SLOT_SIZE": "4096",
        "SLAB_TOTAL_BYTES": "4294967296",
        "NR_ASYNC_REPL": async_repl,
    }, run_lines)

    # Wait for UDS + heartbeat to fully stabilize after restart
    for _ in range(30):
        if Path(uds).is_socket():
            break
        time.sleep(0.5)
    time.sleep(float(os.environ.get("PF1_READY_WAIT_S", "1")))

    ops_per_sec = 0.0
    ops_fail = 0
    ops_degraded = 0
    ops_raw: dict = {}
    passed_ops = False
    best_threads_ops = int(os.environ.get("OPS_THREADS", "4"))
    batch = os.environ.get("BATCH", "64")

    if Path(uds).is_socket():
        # Wait briefly for heartbeat + RDMA poller to stabilize after restart.
        time.sleep(float(os.environ.get("PF1_OPS_STABILIZE_S", "1")))

        # Measured run (directly on fresh data plane, no probe/warmup overhead)
        cmd = [
            str(bin_path), f"--uds={uds}", "--op=put", f"--threads={best_threads_ops}",
            "--val-size=1024", f"--duration={ops_dur}", f"--require-peer={require_peer}",
            f"--batch={batch}",
        ]
        proc = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        run_lines.append(f"[measured-ops] $ {' '.join(cmd)}\nexit={proc.returncode}\n{proc.stdout}\n")
        ops_raw = parse_bench_output(proc.stdout)

        ops_per_sec = float(ops_raw.get("ops_per_sec", 0))
        ops_fail = int(ops_raw.get("ops_fail", 0))
        ops_degraded = int(ops_raw.get("ops_degraded", 0))
        passed_ops = ops_per_sec >= 1_000_000 and ops_fail == 0 and ops_degraded == 0

    # ================================================================
    # Combined result
    # ================================================================
    ops_ok = int(ops_raw.get("ops_ok", 0))
    ops_total = ops_ok + ops_fail
    ops_fail_pct = (ops_fail / ops_total * 100.0) if ops_total > 0 else 0.0
    ops_success_rate_pct = (ops_ok / ops_total * 100.0) if ops_total > 0 else 0.0
    bw_ops_ok = int(bw_raw.get("ops_ok", 0))
    bw_total = bw_ops_ok + bw_fail
    bw_fail_pct = (bw_fail / bw_total * 100.0) if bw_total > 0 else 0.0
    bw_success_rate_pct = (bw_ops_ok / bw_total * 100.0) if bw_total > 0 else 0.0
    passed = passed_ops and passed_util

    restore_lines: list[str] = []
    restore_ok = restart_stack(native_root, {
        "SLAB_SLOT_SIZE": "4096",
        "SLAB_TOTAL_BYTES": "4294967296",
        "NR_ASYNC_REPL": restore_async_repl,
    }, restore_lines)
    run_lines.append("\n" + "=" * 60 + "\nRestore functional data-plane defaults\n" + "=" * 60 + "\n")
    run_lines.extend(restore_lines)
    if not restore_ok:
        run_lines.append("[ERROR] Failed to restore 4KB functional data-plane defaults\n")
        passed = False

    result = {
        "metric": "perf_01",
        # Sub-test A
        "ops_threads": best_threads_ops,
        "ops_val_size": int(ops_raw.get("val_size", 1024)),
        "ops_per_sec": ops_per_sec,
        "ops_ok": ops_ok,
        "ops_fail": ops_fail,
        "ops_fail_pct": round(ops_fail_pct, 3),
        "ops_success_rate_pct": round(ops_success_rate_pct, 3),
        "ops_degraded": ops_degraded,
        "passed_ops": bool(passed_ops),
        # Sub-test B
        "bw_threads": bw_threads,
        "bw_val_size": bw_val_size,
        "bw_write_gbps": round(bw_write_gbps, 3),
        "bw_network_tx_gbps_avg": round(bw_network_tx_gbps_avg, 3),
        "bw_network_tx_gbps_peak": round(bw_network_tx_gbps_peak, 3),
        "bw_link_gbps": link_gbps,
        "bw_util_pct": round(bw_util_pct, 2),
        "bw_ok": bw_ops_ok,
        "bw_fail": bw_fail,
        "bw_fail_pct": round(bw_fail_pct, 3),
        "bw_success_rate_pct": round(bw_success_rate_pct, 3),
        "bw_degraded": bw_degraded,
        "passed_util": bool(passed_util),
        "bw_trials": bw_trials,
        "restore_async_repl": restore_async_repl,
        "restore_ok": bool(restore_ok),
        # Overall
        "thresholds": {
            "ops_per_sec": 1_000_000,
            "util_pct": 50.0,
            "fail": 0,
            "degraded": 0,
            "criterion": "ops AND util (分项验收)",
        },
        "passed": bool(passed),
        "raw_ops": ops_raw,
        "raw_bw": bw_raw,
    }
    ts = time.strftime("%Y%m%d_%H%M%S")
    write_json(logs / f"perf_01_{ts}.json", result)
    write_json(raw_json, result)
    run_log.write_text("\n".join(run_lines), encoding="utf-8")
    write_summary(path, result, run_log, raw_json)
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
