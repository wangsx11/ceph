#!/usr/bin/env python3
"""PF-6: 多级存储读写能力

Thresholds:
  - 写入 >= 10 GB/s
  - 读取 >= 20 GB/s
  - 读命中比例在 [0.95, 1.05] 范围内

需要 SLAB_SLOT_SIZE=1048576 (1MB) 才能接受大对象。
测试会自动重启数据面设置 1MB slab，完成后恢复 4KB slab。
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


PF_ID = "PF-6"
PF_NAME = "多级存储读写能力"
SOURCE_NO = 6
THRESHOLD = "写入 >= 10GB/s；读取 >= 20GB/s"
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
    m = re.search(rf"req_bytes\s*:\s*(\d+)\s*\(({NUM})\s*MB/s\)", text)
    if m:
        out["req_bytes"] = int(m.group(1))
    m = re.search(rf"resp_bytes\s*:\s*(\d+)\s*\(({NUM})\s*MB/s\)", text)
    if m:
        out["resp_bytes"] = int(m.group(1))
    m = re.search(r"val_size=(\d+)", text)
    if m:
        out["val_size"] = int(m.group(1))
    return out


def write_json(path: Path, data: dict) -> None:
    if "passed" in data and "status" not in data:
        data["status"] = "PASS" if data.get("passed") else "FAIL"
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def restart_stack(native_root: Path, env_extra: dict, run_lines: list[str]) -> bool:
    env = os.environ.copy()
    env.update(env_extra)
    proc = subprocess.run(
        ["bash", str(native_root / "start.sh")],
        text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        cwd=str(native_root), env=env, timeout=120,
    )
    run_lines.append(f"[restart] env: {env_extra}\n[restart] exit={proc.returncode}\n")
    return proc.returncode == 0


def run_bench(bin_path: Path, uds: str, op: str, dur: str, threads: str,
              val_size: str, keyspace: str, require_peer: str,
              batch: str = "1", run_lines: list[str] | None = None) -> tuple[dict, str]:
    cmd = [
        str(bin_path), f"--uds={uds}", f"--op={op}", f"--threads={threads}",
        f"--val-size={val_size}", f"--duration={dur}", f"--keyspace={keyspace}",
        "--shared-keyspace=1", f"--require-peer={require_peer}",
    ]
    if int(batch) > 1:
        cmd.append(f"--batch={batch}")
    proc = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    log_entry = f"$ {' '.join(cmd)}\nexit={proc.returncode}\n{proc.stdout}\n"
    if run_lines is not None:
        run_lines.append(log_entry)
    return parse_bench_output(proc.stdout), proc.stdout


def write_summary(path: Path, result: dict, run_log: Path, raw_json: Path) -> None:
    lines = [
        f"# {PF_ID} Summary",
        "",
        f"- Metric: {PF_NAME}",
        f"- Source: `docs/性能要求.md` 第 {SOURCE_NO} 条",
        f"- Generated At: {time.strftime('%Y-%m-%dT%H:%M:%S%z')}",
        f"- Key Result: write={result.get('write_gbs', 'N/A')} GB/s, read={result.get('read_gbs', 'N/A')} GB/s",
        f"- Threshold: {THRESHOLD}",
        f"- Result: {'PASS' if result.get('passed') else 'FAIL'}",
        f"- Result Dir: {path.resolve()}",
        f"- Raw JSON: {raw_json.resolve()}",
        f"- Run Log: {run_log.resolve()}",
        "",
        "## 写入测试",
        "",
        "| Key | Value |",
        "|---|---:|",
    ]
    for key in ("write_gbs", "write_tx_bytes", "write_ops", "write_fail", "write_degraded"):
        lines.append(f"| `{key}` | {result.get(key, 'N/A')} |")
    lines.extend([
        "",
        "## 读取测试",
        "",
        "| Key | Value |",
        "|---|---:|",
    ])
    for key in ("read_gbs", "read_rx_bytes", "read_ops_total", "read_fail",
                "read_avg_resp_bytes", "read_hit_ratio"):
        lines.append(f"| `{key}` | {result.get(key, 'N/A')} |")
    lines.extend([
        "",
        "## 统计口径",
        "",
        "- 写入带宽基于 req_bytes（客户端→服务端实际字节），读取带宽基于 resp_bytes（服务端→客户端实际字节）。",
        "- 1MB 对象，shared keyspace=512。",
        "- 测试前重启数据面设置 SLAB_SLOT_SIZE=1048576。",
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
    write_dur = os.environ.get("WRITE_DUR", os.environ.get("DUR", "5"))
    read_dur = os.environ.get("READ_DUR", os.environ.get("DUR", "10"))
    val_size = os.environ.get("VAL_SIZE", "1048576")
    keyspace = os.environ.get("KEYSPACE", "512")
    require_peer = os.environ.get("REQUIRE_PEER", "1")
    async_repl = os.environ.get("NR_ASYNC_REPL", "1")
    restore_async_repl = os.environ.get("NR_RESTORE_ASYNC_REPL", "0")
    put_threads = os.environ.get("PUT_THREADS", "5")
    put_batch = os.environ.get("PUT_BATCH", "2")
    get_threads = os.environ.get("GET_THREADS", "8")
    drain_seconds = float(os.environ.get("PF6_DRAIN_SECONDS", "8"))
    raw_json = path / "raw.json"
    run_log = logs / "run.log"

    if not os.access(bin_path, os.X_OK):
        result = {"metric": "perf_06", "passed": False, "error": f"nr_bench missing: {bin_path}"}
        write_json(raw_json, result)
        run_log.write_text(result["error"] + "\n", encoding="utf-8")
        write_summary(path, result, run_log, raw_json)
        return 2

    run_lines: list[str] = []

    # Restart with 1MB slab
    restart_ok = restart_stack(native_root, {
        "SLAB_SLOT_SIZE": val_size,
        "SLAB_TOTAL_BYTES": "4294967296",
        "NR_ASYNC_REPL": async_repl,
    }, run_lines)
    if not restart_ok:
        result = {"metric": "perf_06", "passed": False, "error": "restart failed"}
        write_json(raw_json, result)
        run_log.write_text("\n".join(run_lines), encoding="utf-8")
        write_summary(path, result, run_log, raw_json)
        return 2

    for _ in range(30):
        if Path(uds).is_socket():
            break
        time.sleep(0.5)
    time.sleep(3)

    # WRITE phase
    run_lines.append("[write]\n")
    jw, _ = run_bench(bin_path, uds, "put", write_dur, put_threads, val_size, keyspace,
                      require_peer, batch=put_batch, run_lines=run_lines)

    if drain_seconds > 0:
        run_lines.append(f"\n[drain] wait {drain_seconds:.1f}s for async RDMA completions before read phase\n")
        time.sleep(drain_seconds)

    # READ phase
    run_lines.append("\n[read]\n")
    jr, _ = run_bench(bin_path, uds, "get-raw", read_dur, get_threads, val_size, keyspace,
                      require_peer, run_lines=run_lines)

    # Compute metrics
    elapsed_w = float(jw.get("elapsed_s", 1.0)) or 1.0
    elapsed_r = float(jr.get("elapsed_s", 1.0)) or 1.0
    w_tx = int(jw.get("req_bytes", 0))
    r_rx = int(jr.get("resp_bytes", 0))
    w_gbs = (w_tx / elapsed_w) / 1e9
    r_gbs = (r_rx / elapsed_r) / 1e9

    wfail = int(jw.get("ops_fail", 0))
    wdegr = int(jw.get("ops_degraded", 0))
    wok = int(jw.get("ops_ok", 0))
    w_fail_pct = (wfail / (wok + wfail) * 100) if (wok + wfail) > 0 else 0
    rfail = int(jr.get("ops_fail", 0))
    r_total = int(jr.get("ops_ok", 0))
    vsz = int(val_size)
    avg_resp = (r_rx / r_total) if r_total > 0 else 0
    hit_ratio = avg_resp / vsz if vsz > 0 else 0

    passed = bool(
        w_gbs >= 10.0 and r_gbs >= 20.0
        and 0.95 <= hit_ratio <= 1.05
        and w_fail_pct < 10.0
        and wdegr == 0 and rfail == 0
    )

    note = ""
    if hit_ratio < 0.95 and r_total > 0:
        note = f"LOW HIT RATIO {hit_ratio:.4f}: GETs mostly missed"
    elif hit_ratio > 1.05 and r_total > 0:
        note = f"ANOMALOUS HIT RATIO {hit_ratio:.4f}"

    result = {
        "metric": "perf_06_tier_bw",
        "val_size": vsz,
        "keyspace": int(keyspace),
        "write_duration_s": float(write_dur),
        "read_duration_s": float(read_dur),
        "write_gbs": round(w_gbs, 3),
        "write_ops": float(jw.get("ops_per_sec", 0)),
        "write_fail": wfail,
        "write_degraded": wdegr,
        "write_tx_bytes": w_tx,
        "read_gbs": round(r_gbs, 3),
        "read_ops_total": r_total,
        "read_fail": rfail,
        "read_rx_bytes": r_rx,
        "read_avg_resp_bytes": int(avg_resp),
        "read_hit_ratio": round(hit_ratio, 4),
        "passed": passed,
        "note": note,
        "raw_put": jw,
        "raw_get": jr,
    }

    ts = time.strftime("%Y%m%d_%H%M%S")
    write_json(logs / f"perf_06_tier_bw_{ts}.json", result)
    write_json(raw_json, result)
    run_log.write_text("\n".join(run_lines), encoding="utf-8")
    write_summary(path, result, run_log, raw_json)

    # Restore 4KB slab
    run_lines_restore: list[str] = []
    restore_ok = restart_stack(native_root, {
        "SLAB_SLOT_SIZE": "4096",
        "SLAB_TOTAL_BYTES": "4294967296",
        "NR_ASYNC_REPL": restore_async_repl,
    }, run_lines_restore)
    result["restore_async_repl"] = restore_async_repl
    result["restore_ok"] = bool(restore_ok)
    if not restore_ok:
        result["passed"] = False
        result["note"] = (result.get("note") or "") + " restore failed"
    run_log.write_text("\n".join(run_lines + ["\n[restore]\n"] + run_lines_restore), encoding="utf-8")
    write_json(raw_json, result)
    write_summary(path, result, run_log, raw_json)

    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
