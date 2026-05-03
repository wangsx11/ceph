#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
REPO_ROOT = ROOT.parent
sys.path.insert(0, str(ROOT))

from common.catalog import all_specs  # noqa: E402


STATUSES = ("PASS", "FAIL", "SKIP", "WAIVED")


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
    incomplete = [row for row in rows if row.get("status") in {"FAIL", "SKIP"}]
    lines = [
        f"# Functions Summary ({finished_at})",
        "",
        f"- Total: {total}",
        f"- PASS: {total_counts['PASS']}",
        f"- FAIL: {total_counts['FAIL']}",
        f"- SKIP: {total_counts['SKIP']}",
        f"- WAIVED: {total_counts['WAIVED']}",
        f"- Result: {'PASS' if total_counts['FAIL'] == 0 else 'FAIL'}",
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
    lines.extend(["", "## 未完成项", ""])
    if incomplete:
        for row in incomplete:
            ev = "; ".join(str(x) for x in row.get("evidence", [])) or "无证据"
            lines.append(f"- {row['module']}/{row['fn_id']} {row.get('status')}: {ev}")
    else:
        lines.append("- 无 FAIL/SKIP 项。")
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
        proc = subprocess.run(
            cmd,
            cwd=str(fn_dir),
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        stdio = (
            "Command: " + " ".join(cmd) + "\n"
            f"Exit Code: {proc.returncode}\n\n"
            "## STDOUT\n" + (proc.stdout or "") + "\n\n"
            "## STDERR\n" + (proc.stderr or "") + "\n"
        )
        (fn_dir / "run_all.last.log").write_text(stdio, encoding="utf-8")
        log_lines.append(f"## {module}/{fn_id} rc={proc.returncode}\n{stdio}")
        raw = _load_raw(fn_dir)
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
    fail_count = sum(1 for row in rows if row["status"] == "FAIL")
    return 0 if fail_count == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

