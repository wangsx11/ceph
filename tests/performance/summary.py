#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""汇总 reports/ 目录内所有 JSON，打印 markdown 表格。"""
import glob
import json
import os
import sys

HERE = os.path.dirname(__file__)
RPT = os.path.join(HERE, "..", "reports")


def main():
    files = sorted(glob.glob(os.path.join(RPT, "*.json")))
    if not files:
        print("no reports yet")
        return 1
    print("| 指标 | 实测 | 目标 | 结果 |")
    print("|------|------|------|------|")
    all_pass = True
    for p in files:
        with open(p) as f:
            r = json.load(f)
        flag = "✅" if r["pass"] else "❌"
        all_pass &= r["pass"]
        print(f"| {r['metric']} | {r['value']:.3f}{r.get('unit','')} | "
              f"{r['target']}{r.get('unit','')} | {flag} |")
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
