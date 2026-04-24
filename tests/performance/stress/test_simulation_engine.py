#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""性能指标 8 — 仿真引擎运行速度 ≥ 1× 实时。

4 节点、10 万实体 (1KB)、100 万事件，需在真实时间内推进完成。

本测试使用 backend_v2 暴露的 `simulation_engine.run(entities, events)`
接口，返回耗时 (s) 与"仿真时间"（内部秒），比值 ≥ 1 即通过。
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "backend_v2"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "common"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from _report import record  # noqa: E402


def main():
    from simulation_engine import run_simulation

    wall_start = time.perf_counter()
    sim_secs = run_simulation(entities=100_000, events=1_000_000, sim_duration_s=60)
    wall_s = time.perf_counter() - wall_start
    ratio = sim_secs / wall_s
    record("simulation_speedup", ratio, target=1.0, unit="x", passed=ratio >= 1.0)


if __name__ == "__main__":
    main()
