# -*- coding: utf-8 -*-
"""M6 模块 Mock 数据生成器 — 分级存储能力演示"""
import hashlib
import json
import math
import random
import threading
import time
from datetime import datetime

from mock.config import (
    M6_COLD_READ_MBS, M6_COLD_READ_STD,
    M6_HOT_READ_GBS, M6_HOT_READ_STD,
    M6_P999_WRITE_LATENCY_MS, M6_P999_WRITE_STD,
    M6_WARM_WRITE_GBS, M6_WARM_WRITE_STD,
)

# 热度阈值（与 config.py 保持一致）
THRESHOLD_HOT = 3.0
THRESHOLD_WARM = 1.0
DEMOTE_HOT = 2.0
DEMOTE_WARM = 0.5
TIME_DECAY_ALPHA = 0.3
TIME_WINDOW = 7200


def _ts():
    return datetime.now().strftime('%H:%M:%S')


def _compute_hash(data):
    if isinstance(data, str):
        data = data.encode('utf-8')
    return hashlib.md5(data).hexdigest()[:8]


def _gauss_clamp(mean, std, lo=None, hi=None):
    val = random.gauss(mean, std)
    if lo is not None:
        val = max(lo, val)
    if hi is not None:
        val = min(hi, val)
    return val


MIL_NAMES = [
    "兵力部署", "侦察情报", "装备清单", "作战计划", "通信记录",
    "弹药储备", "后勤物资", "战术指令", "敌情研判", "防空部署",
    "火力配置", "工事构筑", "指挥通联", "卫勤保障", "测绘数据",
    "预警信息", "电子对抗", "频谱管控", "气象数据", "航线规划",
    "阵地编成", "战斗编组", "补给路线", "伤亡统计", "战场态势",
    "雷达数据", "光电侦察", "无人机航迹", "炮兵诸元", "防化信息",
]


def _mil_name(idx):
    name = MIL_NAMES[idx % len(MIL_NAMES)]
    suffix = f"_{chr(65 + random.randint(0, 25))}{random.randint(1, 99):02d}"
    return name + suffix


class MockTieringModule:
    """Mock 版本的 TieringModule，模拟三层分级存储演示"""

    def __init__(self):
        self._lock = threading.Lock()
        self._running = False
        self._step = 0
        self._migration_events = []
        self._snapshot_events = []
        self._tier_state = {"hot": 0, "warm": 0, "cold": 0}
        self._objects = {}       # name -> {"tier": "hot"/"warm"/"cold", "data": bytes, "cache_layers": [...]}
        self._access_history = {}  # name -> [timestamps]
        self._demo_thread = None

    def _calculate_heat_score(self, obj_id):
        access_times = self._access_history.get(obj_id, [])
        if not access_times:
            return 0.0
        current_time = time.time()
        score = 0.0
        for at in access_times:
            diff = current_time - at
            if diff > TIME_WINDOW:
                continue
            score += 1.0 / math.pow(1 + diff, TIME_DECAY_ALPHA)
        return score

    def _record_access(self, obj_id, count=1):
        current_time = time.time()
        if obj_id not in self._access_history:
            self._access_history[obj_id] = []
        for _ in range(count):
            self._access_history[obj_id].append(current_time)
            current_time += 0.01

    def _count_tiers(self):
        hot = warm = cold = 0
        for obj in self._objects.values():
            t = obj["tier"]
            if t == "hot":
                hot += 1
            elif t == "warm":
                warm += 1
            else:
                cold += 1
        self._tier_state = {"hot": hot, "warm": warm, "cold": cold}
        return self._tier_state

    def start_demo(self):
        if self._running:
            return {"error": "演示正在运行中"}

        self._running = True
        self._step = 0
        self._migration_events = []
        self._snapshot_events = []
        self._objects = {}
        self._access_history = {}

        def demo_flow():
            try:
                self._tier_state = {"hot": 0, "warm": 0, "cold": 0}

                # ---- 步骤1: 写入温层 ----
                self._step = 1
                obj_names = []
                for i in range(100):
                    name = _mil_name(i)
                    obj_names.append(name)
                    data = json.dumps({
                        "unit": f"部队{i:03d}",
                        "location": f"区域{chr(65 + i % 26)}",
                        "strength": random.randint(50, 300),
                        "status": random.choice(["就绪", "行军", "战斗", "待命"])
                    }).encode('utf-8')
                    self._objects[name] = {
                        "tier": "warm",
                        "data": data,
                        "cache_layers": ["warm"],
                    }
                self._count_tiers()
                time.sleep(3)

                # ---- 步骤2: 模拟访问 ----
                self._step = 2
                hot_candidates = random.sample(obj_names, 10)
                warm_candidates = random.sample(
                    [n for n in obj_names if n not in hot_candidates], 20
                )
                cold_candidates = [
                    n for n in obj_names
                    if n not in hot_candidates and n not in warm_candidates
                ]

                for name in hot_candidates:
                    self._record_access(name, count=random.randint(15, 25))
                for name in warm_candidates:
                    self._record_access(name, count=random.randint(3, 6))
                time.sleep(3)

                # ---- 步骤3: 冷热识别迁移 ----
                self._step = 3
                demoted = []
                for name in hot_candidates:
                    score = self._calculate_heat_score(name)
                    if score >= THRESHOLD_HOT:
                        # promote warm -> hot
                        self._objects[name]["tier"] = "hot"
                        self._objects[name]["cache_layers"] = ["hot", "warm"]
                        lat_us = _gauss_clamp(35, 5, 20, 60)
                        evt = {
                            "ts": _ts(), "dir": "↑PROMOTE", "obj": name,
                            "from": "温层(SSD)", "to": "热层(DRAM)+温层",
                            "reason": f"热度{score:.1f}>阈值{THRESHOLD_HOT} (缓存提升)",
                            "latency_us": round(lat_us, 1),
                            "read_speed_gbs": round(_gauss_clamp(M6_HOT_READ_GBS, M6_HOT_READ_STD, 18, 22), 1),
                        }
                        self._migration_events.insert(0, evt)
                    time.sleep(0.1)

                for name in cold_candidates:
                    score = self._calculate_heat_score(name)
                    if score < DEMOTE_WARM:
                        # demote warm -> cold
                        self._objects[name]["tier"] = "cold"
                        self._objects[name]["cache_layers"] = ["warm", "cold"]
                        lat_us = _gauss_clamp(200, 30, 100, 400)
                        evt = {
                            "ts": _ts(), "dir": "↓DEMOTE", "obj": name,
                            "from": "温层(SSD)", "to": "温层+冷层(HDD)",
                            "reason": f"热度{score:.1f}<阈值{DEMOTE_WARM} (缓存复制)",
                            "write_speed_gbs": round(_gauss_clamp(M6_WARM_WRITE_GBS, M6_WARM_WRITE_STD, 9, 11), 1),
                        }
                        self._migration_events.insert(0, evt)
                        demoted.append(name)
                    time.sleep(0.05)
                self._count_tiers()
                time.sleep(3)

                # ---- 步骤4: 冷数据备份 ----
                self._step = 4
                if demoted:
                    snap_name = f"backup_{datetime.now().strftime('%Y-%m-%d_%H%M%S')}"
                    t0 = time.time()
                    snapshot_data = {}
                    for obj_id in demoted:
                        obj = self._objects.get(obj_id)
                        if obj:
                            snapshot_data[obj_id] = {
                                "size": len(obj["data"]),
                                "hash": _compute_hash(obj["data"]),
                            }
                    dur = time.time() - t0 + random.uniform(0.3, 0.8)
                    evt = {
                        "ts": _ts(), "name": snap_name,
                        "count": len(snapshot_data), "dur": f"{dur:.2f}",
                        "storage": "ceph_backup_pool",
                    }
                    self._snapshot_events.insert(0, evt)
                time.sleep(3)

                # ---- 步骤5: 回访回迁 ----
                self._step = 5
                revisit_pool = cold_candidates[:len(cold_candidates) // 2]
                revisit = random.sample(revisit_pool, min(5, len(revisit_pool)))
                for name in revisit:
                    self._record_access(name, count=random.randint(8, 15))
                    score = self._calculate_heat_score(name)
                    if score >= THRESHOLD_WARM:
                        self._objects[name]["tier"] = "warm"
                        self._objects[name]["cache_layers"] = ["warm", "cold"]
                        evt = {
                            "ts": _ts(), "dir": "↑PROMOTE", "obj": name,
                            "from": "冷层(HDD)", "to": "温层(SSD)+冷层",
                            "reason": f"热度{score:.1f}>阈值{THRESHOLD_WARM} (缓存提升)",
                            "read_speed_mbs": round(_gauss_clamp(M6_COLD_READ_MBS, M6_COLD_READ_STD, 200, 300), 0),
                        }
                        self._migration_events.insert(0, evt)
                    time.sleep(0.2)
                self._count_tiers()
                time.sleep(3)

                # ---- 步骤6: 再次分层 ----
                self._step = 6
                for name in warm_candidates[:5]:
                    self._record_access(name, count=random.randint(12, 20))
                    score = self._calculate_heat_score(name)
                    if score >= THRESHOLD_HOT:
                        self._objects[name]["tier"] = "hot"
                        self._objects[name]["cache_layers"] = ["hot", "warm"]
                        evt = {
                            "ts": _ts(), "dir": "↑PROMOTE", "obj": name,
                            "from": "温层(SSD)", "to": "热层(DRAM)+温层",
                            "reason": f"热度{score:.1f}>阈值{THRESHOLD_HOT} (缓存提升)",
                            "read_speed_gbs": round(_gauss_clamp(M6_HOT_READ_GBS, M6_HOT_READ_STD, 18, 22), 1),
                        }
                        self._migration_events.insert(0, evt)
                    time.sleep(0.1)
                self._count_tiers()
                time.sleep(2)

                self._step = 7  # 完成
            except Exception as e:
                print(f"[M6-Mock] Demo error: {e}")
                import traceback
                traceback.print_exc()
            finally:
                self._running = False

        self._demo_thread = threading.Thread(target=demo_flow, daemon=True)
        self._demo_thread.start()
        return {"started": True}

    def get_status(self):
        self._count_tiers()
        mig = self._migration_events[:30]
        snap = self._snapshot_events[:10]
        return {
            "running": self._running,
            "step": self._step,
            "tier_state": self._tier_state,
            "migration_events": mig,
            "snapshot_events": snap,
        }

    def get_object_details(self):
        result = []
        for name, obj in self._objects.items():
            score = self._calculate_heat_score(name)
            result.append({
                "name": name,
                "tier": obj["tier"],
                "heat_score": round(score, 2),
                "cache_layers": list(obj["cache_layers"]),
            })
        return result

    def reset(self):
        if self._running:
            self._running = False
            time.sleep(2)
        self._step = 0
        self._migration_events = []
        self._snapshot_events = []
        self._objects = {}
        self._access_history = {}
        self._tier_state = {"hot": 0, "warm": 0, "cold": 0}
        return {"ok": True}
