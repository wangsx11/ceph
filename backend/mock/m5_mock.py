# -*- coding: utf-8 -*-
"""M5 模块 Mock 数据生成器 — 系统吞吐量与性能测试"""
import json
import os
import random
import threading
import time

from mock.config import M5_PREPARE_SECONDS, M5_ROUNDS, M5_TEST_DURATION


def _gauss_clamp(mean, std, low_factor=0.8, high_factor=1.2):
    """高斯抖动，限制在 mean * [low_factor, high_factor] 范围"""
    val = random.gauss(mean, std)
    return max(mean * low_factor, min(mean * high_factor, val))


class MockPerfModule:
    """Mock 版本的 PerfModule，模拟三轮递减性能数据"""

    def __init__(self):
        self._running = False
        self._phase = "idle"
        self._results = {}
        self._results_b = {}
        self._summary = {}
        self._node_mode = {}
        self._lock = threading.Lock()
        self.current_node = os.environ.get("CURRENT_NODE", "A")

    def start_round(self, round_num):
        if self._running:
            return {"error": "测试正在运行中"}

        cfg = M5_ROUNDS.get(round_num, M5_ROUNDS[1])
        obj_count = cfg["count"]
        self._running = True
        self._phase = "preparing"
        self._results[round_num] = []
        self._results_b[round_num] = []

        def run():
            try:
                # 模拟预填充阶段
                self._phase = "preparing"
                time.sleep(M5_PREPARE_SECONDS)

                # 模拟测试阶段：每秒生成一个数据点
                self._phase = "testing"
                for i in range(M5_TEST_DURATION):
                    if not self._running:
                        break

                    # 节点 A 数据点
                    dp_a = {
                        "iops": round(_gauss_clamp(cfg["iops"] * 0.55, cfg["iops_std"] * 0.55), 1),
                        "tp": round(_gauss_clamp(cfg["tp"] * 0.55, cfg["tp_std"] * 0.55), 2),
                        "lat": round(_gauss_clamp(cfg["avg_lat"], cfg["avg_lat_std"]), 2),
                        "rdma": round(_gauss_clamp(cfg["rdma"] * 0.55, cfg["rdma_std"] * 0.55), 2),
                        "net_util": round(_gauss_clamp(cfg["net_util"], cfg["net_util_std"]), 2),
                        "rdma_real": False,
                        "ts": time.time(),
                    }
                    # 节点 B 数据点
                    dp_b = {
                        "iops": round(_gauss_clamp(cfg["iops"] * 0.45, cfg["iops_std"] * 0.45), 1),
                        "tp": round(_gauss_clamp(cfg["tp"] * 0.45, cfg["tp_std"] * 0.45), 2),
                        "lat": round(_gauss_clamp(cfg["avg_lat"], cfg["avg_lat_std"]), 2),
                        "rdma": round(_gauss_clamp(cfg["rdma"] * 0.45, cfg["rdma_std"] * 0.45), 2),
                        "net_util": round(_gauss_clamp(cfg["net_util"], cfg["net_util_std"]), 2),
                        "rdma_real": False,
                        "ts": time.time(),
                    }

                    with self._lock:
                        self._results[round_num].append(dp_a)
                        self._results_b[round_num].append(dp_b)

                    time.sleep(1.0)

                # 构建汇总
                self._build_summary(round_num, cfg)
                self._phase = "done"
            except Exception as e:
                print(f"[M5-Mock] 测试出错: {e}")
                self._phase = "done"
            finally:
                self._running = False

        threading.Thread(target=run, daemon=True).start()
        return {"started": True, "round": round_num, "count": obj_count, "dual_node": True}

    def start_round_remote_only(self, round_num):
        """Mock 远程节点启动（在 mock 模式下实际不会被调用）"""
        return {"started": True, "round": round_num, "remote": True}

    def _build_summary(self, round_num, cfg):
        """根据配置基线生成带抖动的汇总数据"""
        all_lats = []
        for _ in range(1000):
            all_lats.append(random.gauss(cfg["avg_lat"], cfg["avg_lat_std"] * 2))
        all_lats.sort()
        n = len(all_lats)

        results_a = self._results.get(round_num, [])
        results_b = self._results_b.get(round_num, [])
        node_a_iops = round(sum(d["iops"] for d in results_a) / max(len(results_a), 1), 1)
        node_b_iops = round(sum(d["iops"] for d in results_b) / max(len(results_b), 1), 1)

        summary = {
            "count": cfg["count"],
            "iops": round(_gauss_clamp(cfg["iops"], cfg["iops_std"]), 1),
            "tp": round(_gauss_clamp(cfg["tp"], cfg["tp_std"]), 2),
            "avg": round(_gauss_clamp(cfg["avg_lat"], cfg["avg_lat_std"]), 2),
            "p50": round(_gauss_clamp(cfg["p50"], cfg["p50_std"]), 2),
            "p90": round(all_lats[int(n * 0.9)], 2),
            "p99": round(_gauss_clamp(cfg["p99"], cfg["p99_std"]), 2),
            "rdma": round(_gauss_clamp(cfg["rdma"], cfg["rdma_std"]), 2),
            "net_util": round(_gauss_clamp(cfg["net_util"], cfg["net_util_std"]), 2),
            "rdma_real": False,
            "node_mode": "dual",
            "total_ops": int(cfg["iops"] * M5_TEST_DURATION),
            "duration": M5_TEST_DURATION,
            "dual_node": True,
            "node_a_iops": node_a_iops,
            "node_b_iops": node_b_iops,
        }

        with self._lock:
            self._summary[round_num] = summary

    def get_status(self):
        with self._lock:
            return {
                "running": self._running,
                "results": dict(self._results),
                "summary": dict(self._summary),
            }

    def get_live_data(self, round_num):
        with self._lock:
            return {
                "running": self._running,
                "phase": self._phase,
                "round": round_num,
                "data_points": list(self._results.get(round_num, [])),
                "summary": self._summary.get(round_num, None),
            }

    def reset(self):
        if self._running:
            self._running = False
            time.sleep(2)
        with self._lock:
            self._results = {}
            self._results_b = {}
            self._summary = {}
            self._node_mode = {}
        return {"ok": True}
