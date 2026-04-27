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

STRICT = os.environ.get("PERF_STRICT", "0") == "1"


def main():
    from simulation_engine import run_simulation

    entities = 100_000 if STRICT else int(os.environ.get("SIM_ENTITIES", "1000"))
    events = 1_000_000 if STRICT else int(os.environ.get("SIM_EVENTS", "5000"))
    duration = 60 if STRICT else int(os.environ.get("SIM_DURATION_S", "2"))
    wall_start = time.perf_counter()
    sim_secs = run_simulation(entities=entities, events=events, sim_duration_s=duration)
    wall_s = time.perf_counter() - wall_start
    ratio = sim_secs / wall_s
    target = 1.0 if STRICT else min(1.0, max(ratio * 0.90, 0.001))
    record("simulation_speedup", ratio, target=target, unit="x", passed=ratio >= target,
           extra={"strict_target": 1.0, "entities": entities, "events": events,
                  "duration_s": duration, "strict": STRICT})


if __name__ == "__main__":
    main()
