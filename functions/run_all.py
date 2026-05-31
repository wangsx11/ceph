#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import socket
import subprocess
import struct
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
REPO_ROOT = ROOT.parent
sys.path.insert(0, str(ROOT))

from common.catalog import all_specs  # noqa: E402


STATUSES = ("PASS", "FAIL", "SKIP", "WAIVED")
START_SCRIPT = REPO_ROOT / "native_rdma" / "start.sh"


def _stamp() -> str:
    return time.strftime("%Y%m%d_%H%M%S")


def _iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def _load_raw(fn_dir: Path) -> dict[str, Any]:
    raw = fn_dir / "raw.json"
    if not raw.exists():
        return {"status": "FAIL", "evidence": ["raw.json not generated"], "raw_json": str(raw)}
    try:
        return json.loads(raw.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"status": "FAIL", "evidence": [f"raw.json parse failed: {exc}"], "raw_json": str(raw)}


def _fn_env(module: str, fn_id: str, base_env: dict[str, str]) -> dict[str, str]:
    env = dict(base_env)
    if module == "rdma" and fn_id == "FN-1":
        env.update({
            "NR_TRANSPORT": "tcp",
            "NR_ASYNC_REPL": "0",
            "NR_GDR_ENABLE": "0",
            "NR_SKIP_FLASK": "1",
            "NR_RESTART_BEFORE_FUNCTION": "1",
            "NR_RESTART_STABILIZE_SECONDS": "5",
            "NR_RESTORE_AFTER_FUNCTION": "1",
            "NR_RESTORE_TRANSPORT": "rdma",
            "NR_RESTORE_ASYNC_REPL": "0",
            "NR_RESTORE_GDR_ENABLE": "0",
            "NR_RESTORE_WAIT_TIMEOUT": "45",
        })
    if module == "rdma" and fn_id == "FN-4":
        env.update({
            "NR_TRANSPORT": "rdma",
            "NR_ASYNC_REPL": "0",
            "NR_GDR_ENABLE": "1",
            "NR_SKIP_FLASK": "1",
            "NR_RESTART_BEFORE_FUNCTION": "1",
            "NR_RESTART_STABILIZE_SECONDS": "5",
            "NR_RESTORE_AFTER_FUNCTION": "1",
            "NR_RESTORE_TRANSPORT": "rdma",
            "NR_RESTORE_ASYNC_REPL": "0",
            "NR_RESTORE_GDR_ENABLE": "0",
            "NR_RESTORE_WAIT_TIMEOUT": "45",
        })
    if module == "mempool" and fn_id == "FN-6":
        env.update({
            "ALLOW_DESTRUCTIVE": "1",
            "PEER_SSH": env.get("PEER_SSH") or "xfusion4",
            "PEER_DP_PATH": env.get("PEER_DP_PATH")
                or str(REPO_ROOT / "native_rdma" / "build-current" / "bin" / "native_rdma_dp"),
            "FN6_RECOVERY_CMD": env.get("FN6_RECOVERY_CMD")
                or "cd native_rdma && LOCAL_HOST=xfusion3 NR_TRANSPORT=rdma "
                   "NR_ASYNC_REPL=0 NR_SKIP_FLASK=1 bash start.sh",
            "NR_TRANSPORT": "rdma",
            "NR_ASYNC_REPL": "0",
        })
    return env


def _restart_stack(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(START_SCRIPT)],
        cwd=str(REPO_ROOT / "native_rdma"),
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=240,
    )


def _restore_env(env: dict[str, str]) -> dict[str, str]:
    restore = dict(env)
    restore["NR_TRANSPORT"] = env.get("NR_RESTORE_TRANSPORT", "rdma")
    restore["NR_ASYNC_REPL"] = env.get("NR_RESTORE_ASYNC_REPL", "0")
    restore["NR_GDR_ENABLE"] = env.get("NR_RESTORE_GDR_ENABLE", "0")
    restore["NR_SKIP_FLASK"] = "1"
    restore.pop("NR_RESTART_BEFORE_FUNCTION", None)
    restore.pop("NR_RESTORE_AFTER_FUNCTION", None)
    restore.pop("NR_RESTART_STABILIZE_SECONDS", None)
    restore.pop("NR_RESTORE_TRANSPORT", None)
    restore.pop("NR_RESTORE_ASYNC_REPL", None)
    restore.pop("NR_RESTORE_GDR_ENABLE", None)
    restore.pop("NR_RESTORE_WAIT_TIMEOUT", None)
    return restore


def _recv_exact(sock: socket.socket, size: int) -> bytes:
    out = b""
    while len(out) < size:
        chunk = sock.recv(size - len(out))
        if not chunk:
            raise ConnectionError(f"short read: expected {size}, got {len(out)}")
        out += chunk
    return out


def _uds_json(uds_path: str, kind: str, timeout: float = 2.0) -> dict[str, Any]:
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        sock.connect(uds_path)
        kind_b = kind.encode()
        sock.sendall(struct.pack("<I", len(kind_b)) + kind_b + struct.pack("<I", 0))
        resp_size = struct.unpack("<I", _recv_exact(sock, 4))[0]
        data = _recv_exact(sock, resp_size)
        return json.loads(data.decode("utf-8", errors="replace"))
    finally:
        sock.close()


def _wait_for_restored_peer(env: dict[str, str]) -> tuple[bool, str]:
    timeout_s = float(env.get("NR_RESTORE_WAIT_TIMEOUT", "30") or "30")
    interval_s = float(env.get("NR_RESTORE_WAIT_INTERVAL", "0.5") or "0.5")
    desired_transport = env.get("NR_RESTORE_TRANSPORT", env.get("NR_TRANSPORT", "rdma"))
    uds_path = env.get("UDS", "/tmp/native_rdma-dp.sock")
    deadline = time.time() + timeout_s
    last: dict[str, Any] = {"ok": False, "err": "not sampled"}
    while time.time() < deadline:
        try:
            last = _uds_json(uds_path, "RPC_CLUSTER_STATUS")
            ready = (
                last.get("ok") is True
                and last.get("peer_alive") is True
                and last.get("tcp_data_ready") is True
                and str(last.get("transport", "")) == str(desired_transport)
            )
            if ready:
                return True, (
                    "peer_ready=true "
                    f"transport={last.get('transport')} "
                    f"peer_num_qp={last.get('peer_num_qp')} "
                    f"tcp_data_ready={last.get('tcp_data_ready')}"
                )
        except Exception as exc:
            last = {"ok": False, "err": repr(exc)}
        time.sleep(interval_s)
    return False, "last_cluster_status=" + json.dumps(last, ensure_ascii=False, sort_keys=True)


def _module_summary(rows: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {}
    for row in rows:
        mod = str(row["module"])
        out.setdefault(mod, {status: 0 for status in STATUSES})
        status = str(row.get("status", "FAIL"))
        out[mod][status if status in STATUSES else "FAIL"] += 1
    return out


def _write_summary(rows: list[dict[str, Any]], run_log: Path, finished_at: str) -> None:
    module_counts = _module_summary(rows)
    total_counts = {status: sum(counts.get(status, 0) for counts in module_counts.values()) for status in STATUSES}
    total = len(rows)
    incomplete = [row for row in rows if row.get("status") in {"FAIL", "SKIP", "WAIVED"}]
    overall_pass = (
        total_counts["FAIL"] == 0
        and total_counts["SKIP"] == 0
        and total_counts["WAIVED"] == 0
    )
    result = "PASS" if overall_pass else "FAIL"
    lines = [
        f"# Functions Summary ({finished_at})",
        "",
        f"- Total: {total}",
        f"- PASS: {total_counts['PASS']}",
        f"- FAIL: {total_counts['FAIL']}",
        f"- SKIP: {total_counts['SKIP']}",
        f"- WAIVED: {total_counts['WAIVED']}",
        f"- Result: {result}",
        f"- Run All Log: {run_log}",
        "",
        "## 模块汇总",
        "",
        "| Module | Total | PASS | FAIL | SKIP | WAIVED |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for module in ("storage", "rdma", "mempool"):
        counts = module_counts.get(module, {status: 0 for status in STATUSES})
        mod_total = sum(counts.values())
        lines.append(
            f"| {module} | {mod_total} | {counts['PASS']} | {counts['FAIL']} | {counts['SKIP']} | {counts['WAIVED']} |"
        )
    lines.extend([
        "",
        "## 功能点结果",
        "",
        "| Module | FN | Function | Result | Completion | Summary |",
        "|---|---|---|---|---|---|",
    ])
    for row in rows:
        lines.append(
            f"| {row['module']} | {row['fn_id']} | {row['function']} | "
            f"{row.get('status', 'FAIL')} | {row.get('completion', '未完成')} | "
            f"`{row['summary']}` |"
        )
    lines.extend(["", "## 未通过/豁免项", ""])
    if incomplete:
        for row in incomplete:
            ev = "; ".join(str(x) for x in row.get("evidence", [])) or "无证据"
            lines.append(f"- {row['module']}/{row['fn_id']} {row.get('status')}: {ev}")
    else:
        lines.append("- 无 FAIL/SKIP/WAIVED 项。")
    (ROOT / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    run_ts = os.environ.get("RUN_ALL_TS", _stamp())
    log_dir = ROOT / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    run_log = log_dir / f"run_all_{run_ts}.log"
    env = os.environ.copy()
    env.setdefault("REPO_ROOT", str(REPO_ROOT))
    env.setdefault("PYTHONUNBUFFERED", "1")
    rows: list[dict[str, Any]] = []
    log_lines: list[str] = [f"run_all start {_iso()}"]

    for spec in all_specs():
        module = str(spec["module"])
        fn_id = str(spec["fn_id"])
        fn_dir = ROOT / module / fn_id
        cmd = ["bash", str(fn_dir / "run.sh")]
        print(f"==> {module}/{fn_id} {spec['name']}", flush=True)
        fn_env = _fn_env(module, fn_id, env)
        raw_path = fn_dir / "raw.json"
        raw_mtime_before = raw_path.stat().st_mtime if raw_path.exists() else 0.0
        preface = ""
        restore_text = ""
        try:
            if fn_env.get("NR_RESTART_BEFORE_FUNCTION") == "1":
                restart = _restart_stack(fn_env)
                preface += (
                    "[functions/run_all] restart stack before function\n"
                    f"Command: bash {START_SCRIPT}\n"
                    f"Exit Code: {restart.returncode}\n\n"
                    f"{restart.stdout or ''}\n"
                )
                if restart.returncode != 0:
                    raise RuntimeError(f"restart stack failed with exit {restart.returncode}")
                try:
                    stabilize_s = float(fn_env.get("NR_RESTART_STABILIZE_SECONDS", "0") or "0")
                except ValueError:
                    stabilize_s = 0.0
                if stabilize_s > 0:
                    preface += f"[functions/run_all] wait {stabilize_s:.1f}s for heartbeat stabilization\n"
                    time.sleep(stabilize_s)
            proc = subprocess.run(
                cmd,
                cwd=str(fn_dir),
                env=fn_env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except Exception as exc:
            proc = subprocess.CompletedProcess(cmd, 1, "", str(exc))
        finally:
            if fn_env.get("NR_RESTORE_AFTER_FUNCTION") == "1":
                restore_rc = 1
                try:
                    restore = _restart_stack(_restore_env(fn_env))
                    restore_rc = restore.returncode
                    restore_stdout = restore.stdout or ""
                except Exception as exc:
                    restore_stdout = str(exc)
                restore_text = (
                    "\n[functions/run_all] restore stack after function\n"
                    f"Command: bash {START_SCRIPT}\n"
                    f"Exit Code: {restore_rc}\n\n"
                    f"{restore_stdout}\n"
                )
                if restore_rc != 0 and proc.returncode == 0:
                    proc = subprocess.CompletedProcess(
                        cmd,
                        1,
                        proc.stdout,
                        (proc.stderr or "") + f"\nrestore stack failed with exit {restore_rc}",
                    )
                elif restore_rc == 0:
                    restore_ok, restore_wait_msg = _wait_for_restored_peer(fn_env)
                    restore_text += (
                        "\n[functions/run_all] wait for restored peer readiness\n"
                        f"{restore_wait_msg}\n"
                    )
                    if not restore_ok and proc.returncode == 0:
                        proc = subprocess.CompletedProcess(
                            cmd,
                            1,
                            proc.stdout,
                            (proc.stderr or "") + "\nrestore peer readiness timed out: " + restore_wait_msg,
                        )
        stdio = (
            "Command: " + " ".join(cmd) + "\n"
            f"Exit Code: {proc.returncode}\n\n"
            + preface +
            "## STDOUT\n" + (proc.stdout or "") + "\n\n"
            "## STDERR\n" + (proc.stderr or "") + "\n" +
            restore_text
        )
        (fn_dir / "run_all.last.log").write_text(stdio, encoding="utf-8")
        log_lines.append(f"## {module}/{fn_id} rc={proc.returncode}\n{stdio}")
        raw = _load_raw(fn_dir)
        raw_mtime_after = raw_path.stat().st_mtime if raw_path.exists() else 0.0
        if proc.returncode != 0 and raw_mtime_after <= raw_mtime_before:
            raw = {
                "status": "FAIL",
                "completion": "未完成",
                "evidence": [f"runner failed before refreshing raw.json: exit={proc.returncode}"],
                "details": {"stderr": proc.stderr or "", "stdout": proc.stdout or ""},
            }
        elif proc.returncode != 0 and str(raw.get("status", "")).upper() == "PASS":
            raw = dict(raw)
            raw["status"] = "FAIL"
            raw["completion"] = "未完成"
            evidence = list(raw.get("evidence", []))
            evidence.append(f"runner failed after check execution: exit={proc.returncode}")
            raw["evidence"] = evidence
        status = str(raw.get("status", "FAIL"))
        row = {
            "module": module,
            "fn_id": fn_id,
            "function": spec["name"],
            "status": status,
            "completion": raw.get("completion", "未完成"),
            "summary": str(fn_dir / "summary.md"),
            "raw": str(fn_dir / "raw.json"),
            "exit_code": proc.returncode,
            "evidence": raw.get("evidence", []),
        }
        rows.append(row)
        print(f"    {status} {row['completion']}", flush=True)

    finished_at = _iso()
    log_lines.append(f"run_all finished {finished_at}")
    run_log.write_text("\n\n".join(log_lines) + "\n", encoding="utf-8")
    matrix = {
        "generated_at": finished_at,
        "run_log": str(run_log),
        "rows": rows,
    }
    (ROOT / "raw.json").write_text(json.dumps(matrix, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _write_summary(rows, run_log, finished_at)
    not_pass_count = sum(1 for row in rows if row["status"] in {"FAIL", "SKIP", "WAIVED"})
    return 0 if not_pass_count == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
