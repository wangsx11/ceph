# -*- coding: utf-8 -*-
"""共享的结果写盘工具，性能测试统一使用。"""
import json
import os
import time

REPORT_DIR = os.path.join(os.path.dirname(__file__), "..", "reports")
os.makedirs(REPORT_DIR, exist_ok=True)


def record(metric, value, target, unit="", passed=None, extra=None):
    if passed is None:
        passed = value >= target  # default direction – caller overrides
    rec = {
        "metric": metric,
        "value": value,
        "target": target,
        "unit": unit,
        "pass": bool(passed),
        "ts": int(time.time()),
    }
    if extra:
        rec["extra"] = extra
    path = os.path.join(REPORT_DIR, f"{metric}.json")
    with open(path, "w") as f:
        json.dump(rec, f, indent=2)
    flag = "PASS" if passed else "FAIL"
    print(f"[{flag}] {metric}: {value:.3f}{unit} vs target {target}{unit}")
    return rec
