#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import socket
import struct
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import can_connect_uds


PF_ID = "PF-8"
PF_NAME = "RDMA 网络环境下仿真引擎运行能力"
SOURCE_NO = 8
THRESHOLD = "speedup >= 1.0"


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
        f"- Key Result: speedup={result.get('speedup', 'N/A')}x, events/s={result.get('events_per_sec', 'N/A')}",
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
    for key in ("sim_nodes", "entities", "events", "threads", "step_us", "stress", "wall_s", "sim_s", "speedup", "events_per_sec"):
        lines.append(f"| `{key}` | {result.get(key, 'N/A')} |")
    lines.extend([
        "",
        "## 统计口径",
        "",
        "- 测试逻辑由 `native_rdma/tests/performance/perf_08_simulation.sh` 迁移到本 `run.py`。",
        "- 通过数据面 UDS 发送 `RPC_SIM_RUN`，统计仿真运行窗口。",
        "- `speedup = simulated_seconds / wall_seconds`。",
    ])
    note = result.get("error") or result.get("note")
    if note:
        lines.extend(["", "## 说明", "", str(note)])
    (path / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def fail(path: Path, message: str, code: int = 2) -> int:
    logs = log_dir()
    result = {"metric": "perf_08_simulation", "passed": False, "error": message}
    raw_json = path / "raw.json"
    run_log = logs / "run.log"
    write_json(raw_json, result)
    run_log.write_text(message + "\n", encoding="utf-8")
    write_summary(path, result, run_log, raw_json)
    return code


def recv_n(sock: socket.socket, n: int) -> bytes:
    out = b""
    while len(out) < n:
        chunk = sock.recv(n - len(out))
        if not chunk:
            break
        out += chunk
    return out


def main() -> int:
    path = out_dir()
    logs = log_dir()
    raw_json = path / "raw.json"
    run_log = logs / "run.log"
    uds = os.environ.get("UDS", "/tmp/native_rdma-dp.sock")
    if not can_connect_uds(uds):
        return fail(path, f"data plane UDS is not connectable: {uds}; this test requires the data plane.")

    sim_nodes = int(os.environ.get("SIM_NODES", "4"))
    entities = int(os.environ.get("ENTITIES", "100000"))
    events = int(os.environ.get("EVENTS", "1000000"))
    threads = int(os.environ.get("THREADS", "4"))
    step_us = int(os.environ.get("STEP_US", "10"))
    stress = int(os.environ.get("STRESS", "20000"))
    kind = b"RPC_SIM_RUN"
    body = f"entities={entities}&events={events}&threads={threads}&step_us={step_us}&stress={stress}".encode()

    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(600)
        s.connect(uds)
        s.sendall(struct.pack("<I", len(kind)) + kind + struct.pack("<I", len(body)) + body)
        hdr = recv_n(s, 4)
        if len(hdr) != 4:
            raise RuntimeError("short response header from data plane")
        (resp_len,) = struct.unpack("<I", hdr)
        payload = recv_n(s, resp_len).decode(errors="replace")
        s.close()
    except Exception as exc:
        return fail(path, f"RPC_SIM_RUN failed: {exc}")

    run_log.write_text(
        f"UDS={uds}\nRPC=RPC_SIM_RUN\nbody={body.decode()}\nresponse={payload}\n",
        encoding="utf-8",
    )
    try:
        raw = json.loads(payload)
    except Exception as exc:
        raw = {"ok": False, "err": f"parse failed: {exc}", "raw": payload}
    speedup = float(raw.get("speedup", 0))
    result = {
        "metric": "perf_08_simulation",
        "sim_nodes": sim_nodes,
        "entities": raw.get("entities", entities),
        "events": raw.get("events", events),
        "threads": raw.get("threads", threads),
        "step_us": raw.get("step_us", step_us),
        "stress": raw.get("stress", stress),
        "wall_s": raw.get("wall_s", 0),
        "sim_s": raw.get("sim_s", 0),
        "speedup": speedup,
        "events_per_sec": float(raw.get("events_per_sec", 0)),
        "threshold_speedup": 1.0,
        "passed": bool(raw.get("ok", False) and speedup >= 1.0),
        "raw": raw,
    }
    if sim_nodes != 4:
        result["note"] = f"SIM_NODES={sim_nodes}; 指标要求为 4 个节点。"
    ts = time.strftime("%Y%m%d_%H%M%S")
    write_json(logs / f"perf_08_simulation_{ts}.json", result)
    write_json(raw_json, result)
    write_summary(path, result, run_log, raw_json)
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
