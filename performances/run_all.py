#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parent
PF_IDS = [f"PF-{i}" for i in range(1, 10)]


def _fmt(value: object) -> str:
    if isinstance(value, float):
        return f"{value:.3f}".rstrip("0").rstrip(".")
    if value is None:
        return "N/A"
    return str(value)


def _key_result(pf_id: str, data: dict[str, object]) -> str:
    if pf_id == "PF-1":
        return f"{_fmt(data.get('ops_per_sec'))} ops/s, util={_fmt(data.get('util_pct', data.get('bw_util_pct')))}%"
    if pf_id == "PF-2":
        return f"avg={_fmt(data.get('lat_avg_us'))}us, p99={_fmt(data.get('lat_p99_us'))}us"
    if pf_id == "PF-3":
        return f"gain={_fmt(data.get('gain_pct'))}%"
    if pf_id == "PF-4":
        scenario_a = data.get("scenario_a") if isinstance(data.get("scenario_a"), dict) else {}
        scenario_b = data.get("scenario_b") if isinstance(data.get("scenario_b"), dict) else {}
        a_ms = data.get("batches_1000x100_ms", scenario_a.get("elapsed_ms"))
        b_ms = data.get("batches_100x1000_ms", scenario_b.get("elapsed_ms"))
        return f"A={_fmt(a_ms)}ms, B={_fmt(b_ms)}ms"
    if pf_id == "PF-5":
        return f"{_fmt(data.get('mb_per_sec'))} MB/s"
    if pf_id == "PF-6":
        return f"write={_fmt(data.get('write_gbs'))} GB/s, read={_fmt(data.get('read_gbs'))} GB/s"
    if pf_id == "PF-7":
        return f"p999={_fmt(data.get('lat_p999_us'))}us, raid5={_fmt(data.get('raid5_confirmed'))}"
    if pf_id == "PF-8":
        return f"speedup={_fmt(data.get('speedup'))}x"
    if pf_id == "PF-9":
        return (
            f"overhead={_fmt(data.get('overhead_pct'))}%, "
            f"savings={_fmt(data.get('savings_pct'))}%, "
            f"scale={_fmt(data.get('scale_gain_pct'))}%"
        )
    return "N/A"


def _load_raw(pf_dir: Path) -> dict[str, object]:
    raw = pf_dir / "raw.json"
    if not raw.exists():
        return {"passed": False, "error": "raw.json not generated"}
    try:
        return json.loads(raw.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"passed": False, "error": f"failed to parse raw.json: {exc}"}


def main() -> int:
    rows: list[dict[str, object]] = []
    env = os.environ.copy()
    env.setdefault("PYTHONUNBUFFERED", "1")

    for pf_id in PF_IDS:
        pf_dir = ROOT / pf_id
        cmd = ["bash", str(pf_dir / "run.sh")]
        print(f"==> {pf_id}", flush=True)
        proc = subprocess.run(
            cmd,
            cwd=str(pf_dir),
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        (pf_dir / "run_all.last.log").write_text(
            "Command: " + " ".join(cmd) + "\n"
            f"Exit Code: {proc.returncode}\n\n"
            "## STDOUT\n" + (proc.stdout or "") + "\n\n"
            "## STDERR\n" + (proc.stderr or "") + "\n",
            encoding="utf-8",
        )
        raw = _load_raw(pf_dir)
        rows.append(
            {
                "pf": pf_id,
                "exit_code": proc.returncode,
                "passed": bool(raw.get("passed", False)),
                "metric": raw.get("metric", pf_id),
                "key_result": _key_result(pf_id, raw),
                "summary": str(pf_dir / "summary.md"),
                "raw": str(pf_dir / "raw.json"),
                "error": raw.get("error") or raw.get("note") or "",
            }
        )
        print(f"    {'PASS' if rows[-1]['passed'] else 'FAIL'} {rows[-1]['key_result']}", flush=True)

    passed_count = sum(1 for row in rows if row["passed"])
    total = len(rows)
    generated_at = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    lines = [
        f"# Performances Summary ({generated_at})",
        "",
        f"- Passed: {passed_count}/{total}",
        f"- Result: {'PASS' if passed_count == total else 'FAIL'}",
        "",
        "| PF | Metric | Key Result | Result | Exit Code |",
        "|---|---|---|---:|---:|",
    ]
    for row in rows:
        result = "PASS" if row["passed"] else "FAIL"
        lines.append(
            f"| {row['pf']} | `{row['metric']}` | {row['key_result']} | "
            f"{result} | {row['exit_code']} |"
        )
    lines.extend(["", "## Result Files"])
    for row in rows:
        lines.append(f"- {row['pf']}: `{row['summary']}` / `{row['raw']}`")
    errors = [row for row in rows if row.get("error")]
    if errors:
        lines.extend(["", "## Notes"])
        for row in errors:
            lines.append(f"- {row['pf']}: {row['error']}")
    (ROOT / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 0 if passed_count == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
