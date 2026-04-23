# -*- coding: utf-8 -*-
"""模块六 (M6): 分级存储能力演示"""
import json
import math
import os
import random
import threading
import time
from datetime import datetime

from flask import Blueprint, Response, jsonify, request

from mock import USE_MOCK

if not USE_MOCK:
    from ceph_manager import ceph_mgr
    from config import (
        BACKUP_POOL, COLD_POOL, DEMOTE_HOT, DEMOTE_WARM, HOT_PATH, MIGRATION_COOLDOWN,
        MIGRATION_FILE, STATS_FILE, THRESHOLD_HOT, THRESHOLD_WARM,
        TIME_DECAY_ALPHA, TIME_WINDOW, TIERING_DATA_DIR, WARM_POOL,
    )
    from utils import compute_hash, mil_name, ts
else:
    from mock.m6_mock import MockTieringModule

# ============================================================
# TieringModule
# ============================================================

class TieringModule:
    """M6: 三层分级存储 — 基于真实Ceph Pool + ramfs"""

    def __init__(self):
        self._ioctx_warm = None
        self._ioctx_cold = None
        self._ioctx_backup = None
        self._lock = threading.Lock()
        self._running = False
        self._step = 0
        self._migration_events = []
        self._snapshot_events = []
        self._tier_state = {"hot": 0, "warm": 0, "cold": 0}
        self._access_history = self._load_json(STATS_FILE, {})
        self._migration_history = self._load_json(MIGRATION_FILE, {})
        self._demo_thread = None
        self._pending_snapshot_objs = []  # 已降级待备份对象列表
        self._access_dirty = False  # 标记是否有未刷盘的访问记录

    def _load_json(self, path, default):
        if os.path.exists(path):
            try:
                with open(path, 'r') as f:
                    return json.load(f)
            except:
                pass
        return default

    def _save_json(self, path, data):
        with open(path, 'w') as f:
            json.dump(data, f, indent=2)

    def _get_warm_ioctx(self):
        if self._ioctx_warm is None:
            ceph_mgr.create_pool(WARM_POOL)
            self._ioctx_warm = ceph_mgr.open_ioctx(WARM_POOL)
        return self._ioctx_warm

    def _get_cold_ioctx(self):
        if self._ioctx_cold is None:
            ceph_mgr.create_pool(COLD_POOL)
            self._ioctx_cold = ceph_mgr.open_ioctx(COLD_POOL)
        return self._ioctx_cold

    def _get_backup_ioctx(self):
        if self._ioctx_backup is None:
            ceph_mgr.create_pool(BACKUP_POOL)
            self._ioctx_backup = ceph_mgr.open_ioctx(BACKUP_POOL)
        return self._ioctx_backup

    def _ensure_hot_path(self):
        os.makedirs(HOT_PATH, exist_ok=True)

    def calculate_heat_score(self, obj_id):
        """计算热度分数"""
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

    def record_access(self, obj_id, count=1):
        """记录访问（延迟写盘，由 flush_access 统一刷盘）"""
        current_time = time.time()
        if obj_id not in self._access_history:
            self._access_history[obj_id] = []
        for _ in range(count):
            self._access_history[obj_id].append(current_time)
            current_time += 0.01
        cutoff = time.time() - TIME_WINDOW * 2
        self._access_history[obj_id] = [t for t in self._access_history[obj_id] if t > cutoff]
        self._access_dirty = True

    def flush_access(self):
        """将内存中的访问记录批量写盘"""
        if self._access_dirty:
            self._save_json(STATS_FILE, self._access_history)
            self._access_dirty = False

    def get_tier(self, obj_id):
        """获取对象最高缓存层级（缓存模式：对象可能同时存在于多层）"""
        hot_file = os.path.join(HOT_PATH, obj_id)
        if os.path.exists(hot_file):
            return "hot"
        try:
            self._get_warm_ioctx().stat(obj_id)
            return "warm"
        except:
            pass
        try:
            self._get_cold_ioctx().stat(obj_id)
            return "cold"
        except:
            return "unknown"

    def get_cache_layers(self, obj_id):
        """获取对象所在的缓存层级列表（缓存模式）"""
        layers = []
        hot_file = os.path.join(HOT_PATH, obj_id)
        if os.path.exists(hot_file):
            layers.append("hot")
        try:
            self._get_warm_ioctx().stat(obj_id)
            layers.append("warm")
        except:
            pass
        try:
            self._get_cold_ioctx().stat(obj_id)
            layers.append("cold")
        except:
            pass
        return layers

    def cache_read(self, obj_id):
        """缓存查找读取：按 Hot → Warm → Cold 逐层查找"""
        hot_file = os.path.join(HOT_PATH, obj_id)
        if os.path.exists(hot_file):
            self.record_access(obj_id)
            try:
                with open(hot_file, 'rb') as f:
                    return f.read()
            except:
                pass

        try:
            data = self._get_warm_ioctx().read(obj_id)
            self._promote_warm_to_hot(obj_id)
            self.record_access(obj_id)
            return data
        except:
            pass

        try:
            data = self._get_cold_ioctx().read(obj_id)
            self._promote_cold_to_warm(obj_id)
            self.record_access(obj_id)
            return data
        except:
            pass

        return None

    def _count_tiers(self):
        """统计各层对象数"""
        self._ensure_hot_path()
        hot = len([f for f in os.listdir(HOT_PATH) if not f.startswith('.')])
        warm = 0
        cold = 0
        try:
            for _ in self._get_warm_ioctx().list_objects():
                warm += 1
        except:
            pass
        try:
            for _ in self._get_cold_ioctx().list_objects():
                cold += 1
        except:
            pass
        self._tier_state = {"hot": hot, "warm": warm, "cold": cold}
        return self._tier_state

    def _promote_cold_to_warm(self, obj_id, score=None):
        """缓存提升: Cold → Warm (复制，不删除源层)"""
        try:
            data = self._get_cold_ioctx().read(obj_id)
            self._get_warm_ioctx().write_full(obj_id, data)
            if score is None:
                score = self.calculate_heat_score(obj_id)
            self._migration_history[obj_id] = time.time()
            evt = {
                "ts": ts(), "dir": "↑PROMOTE", "obj": obj_id,
                "from": "冷层(HDD)", "to": "温层(SSD)+冷层",
                "reason": f"热度{score:.1f}>阈值{THRESHOLD_WARM} (缓存提升)"
            }
            self._migration_events.insert(0, evt)
            return True
        except Exception as e:
            print(f"promote_cold_to_warm failed: {e}")
            return False

    def _promote_warm_to_hot(self, obj_id, score=None):
        """缓存提升: Warm → Hot (复制，不删除源层)"""
        try:
            self._ensure_hot_path()
            data = self._get_warm_ioctx().read(obj_id)
            with open(os.path.join(HOT_PATH, obj_id), 'wb') as f:
                f.write(data)
            if score is None:
                score = self.calculate_heat_score(obj_id)
            self._migration_history[obj_id] = time.time()
            evt = {
                "ts": ts(), "dir": "↑PROMOTE", "obj": obj_id,
                "from": "温层(SSD)", "to": "热层(DRAM)+温层",
                "reason": f"热度{score:.1f}>阈值{THRESHOLD_HOT} (缓存提升)"
            }
            self._migration_events.insert(0, evt)
            return True
        except Exception as e:
            print(f"promote_warm_to_hot failed: {e}")
            return False

    def _demote_hot_to_warm(self, obj_id, score=None):
        """缓存下沉: Hot → Warm (复制，不删除源层)"""
        try:
            self._ensure_hot_path()
            hot_file = os.path.join(HOT_PATH, obj_id)
            with open(hot_file, 'rb') as f:
                data = f.read()
            self._get_warm_ioctx().write_full(obj_id, data)
            if score is None:
                score = self.calculate_heat_score(obj_id)
            self._migration_history[obj_id] = time.time()
            evt = {
                "ts": ts(), "dir": "↓DEMOTE", "obj": obj_id,
                "from": "热层(DRAM)", "to": "热层+温层(SSD)",
                "reason": f"热度{score:.1f}<阈值{DEMOTE_HOT} (缓存复制)"
            }
            self._migration_events.insert(0, evt)
            return True
        except Exception as e:
            print(f"demote_hot_to_warm failed: {e}")
            return False

    def _demote_warm_to_cold(self, obj_id, score=None):
        """缓存下沉: Warm → Cold (复制，不删除源层)，并登记备份任务"""
        try:
            data = self._get_warm_ioctx().read(obj_id)
            self._get_cold_ioctx().write_full(obj_id, data)
            if score is None:
                score = self.calculate_heat_score(obj_id)
            self._migration_history[obj_id] = time.time()
            self._pending_snapshot_objs.append(obj_id)  # 自动登记待备份
            evt = {
                "ts": ts(), "dir": "↓DEMOTE", "obj": obj_id,
                "from": "温层(SSD)", "to": "温层+冷层(HDD)",
                "reason": f"热度{score:.1f}<阈值{DEMOTE_WARM} (缓存复制)"
            }
            self._migration_events.insert(0, evt)
            return True
        except Exception as e:
            print(f"demote_warm_to_cold failed: {e}")
            return False

    def _create_snapshot(self, demoted_objs):
        """冷层快照 — 读取冷层对象数据保存为快照记录文件，不使用pool-level snap"""
        if not demoted_objs:
            return
        now = datetime.now()
        snap_name = f"snapshot_{now.strftime('%Y-%m-%d_%H%M%S')}"
        t0 = time.time()
        try:
            ioctx_cold = self._get_cold_ioctx()
            snapshot_data = {}
            for obj_id in demoted_objs:
                try:
                    data = ioctx_cold.read(obj_id)
                    snapshot_data[obj_id] = {
                        "size": len(data),
                        "hash": compute_hash(data),
                    }
                except:
                    pass

            snap_file = os.path.join(TIERING_DATA_DIR, f"{snap_name}.json")
            with open(snap_file, 'w') as f:
                json.dump({
                    "name": snap_name,
                    "timestamp": now.strftime('%Y-%m-%d %H:%M:%S'),
                    "objects": snapshot_data,
                    "count": len(snapshot_data),
                }, f, indent=2)

            dur = time.time() - t0
            evt = {
                "ts": ts(), "name": snap_name,
                "count": len(snapshot_data), "dur": f"{dur:.2f}",
            }
            self._snapshot_events.insert(0, evt)
            print(f"[M6] 快照已创建: {snap_name}, {len(snapshot_data)}个对象, 耗时{dur:.2f}s")
        except Exception as e:
            print(f"snapshot failed: {e}")

    def _flush_snapshot_to_ceph(self):
        """在 cold_pool 上创建 Ceph 原生快照（COW，毫秒级），
        并生成本地 JSON 元数据文件。"""
        if not self._pending_snapshot_objs:
            return
        objs_to_backup = list(self._pending_snapshot_objs)
        self._pending_snapshot_objs = []

        now = datetime.now()
        snap_name = f"backup_{now.strftime('%Y-%m-%d_%H%M%S')}"
        t0 = time.time()
        try:
            ioctx_cold = self._get_cold_ioctx()

            # Ceph 原生 pool 快照 — copy-on-write，瞬时完成
            ioctx_cold.create_snap(snap_name)

            # 收集快照元数据（读取数据计算 hash，演示对象很小不影响性能）
            snapshot_data = {}
            for obj_id in objs_to_backup:
                try:
                    data = ioctx_cold.read(obj_id)
                    snapshot_data[obj_id] = {
                        "size": len(data),
                        "hash": compute_hash(data),
                    }
                except Exception as e:
                    print(f"[M6] read obj {obj_id} failed: {e}")

            dur = time.time() - t0

            # 写入本地 JSON 元数据（供 /api/m6/snapshot/<name> 读取）
            snap_file = os.path.join(TIERING_DATA_DIR, f"{snap_name}.json")
            with open(snap_file, 'w') as f:
                json.dump({
                    "name": snap_name,
                    "timestamp": now.strftime('%Y-%m-%d %H:%M:%S'),
                    "objects": snapshot_data,
                    "count": len(snapshot_data),
                    "storage": "ceph_pool_snapshot",
                    "pool": COLD_POOL,
                }, f, indent=2)

            evt = {
                "ts": ts(), "name": snap_name,
                "count": len(snapshot_data), "dur": f"{dur:.2f}",
                "storage": "ceph_pool_snapshot",
            }
            self._snapshot_events.insert(0, evt)
            print(f"[M6] 快照已创建(COW): {snap_name}, {len(snapshot_data)}个对象, 耗时{dur:.2f}s")
        except Exception as e:
            print(f"[M6] _flush_snapshot_to_ceph failed: {e}")

    def _clean_pool(self, ioctx):
        """清空一个Pool的所有对象（异步批量删除）"""
        while True:
            keys = [obj.key for obj in ioctx.list_objects()]
            if not keys:
                break
            comps = []
            for k in keys:
                try:
                    comp = ioctx.aio_remove(k)
                    comps.append(comp)
                except:
                    pass
            for comp in comps:
                try:
                    comp.wait_for_complete()
                except:
                    pass

    def _clean_all_tiers(self):
        """彻底清理三层所有数据"""
        ioctx_warm = self._get_warm_ioctx()
        ioctx_cold = self._get_cold_ioctx()
        self._ensure_hot_path()

        # 先删除 cold_pool 上的所有快照（否则有快照时无法删除对象）
        try:
            for snap in ioctx_cold.list_snaps():
                ioctx_cold.remove_snap(snap.name)
        except Exception as e:
            print(f"[M6] clean snaps failed: {e}")

        self._clean_pool(ioctx_warm)
        self._clean_pool(ioctx_cold)

        for f in os.listdir(HOT_PATH):
            try:
                os.remove(os.path.join(HOT_PATH, f))
            except:
                pass

        self._access_history = {}
        self._migration_history = {}
        self._save_json(STATS_FILE, {})
        self._save_json(MIGRATION_FILE, {})
        self._tier_state = {"hot": 0, "warm": 0, "cold": 0}
        print(f"[M6] 清理完成: warm=0, cold=0, hot=0")

    def start_demo(self):
        """启动完整分级存储演示流程"""
        if self._running:
            return {"error": "演示正在运行中"}

        self._running = True
        self._step = 0
        self._migration_events = []
        self._snapshot_events = []

        def demo_flow():
            try:
                print("[M6] 正在清理旧数据...")
                self._clean_all_tiers()
                print("[M6] 清理完成，开始演示")

                ioctx_warm = self._get_warm_ioctx()
                self._ensure_hot_path()

                # ---- 步骤1: 写入温层 ----
                self._step = 1
                obj_names = []
                for i in range(100):
                    name = mil_name(i)
                    obj_names.append(name)
                    data = json.dumps({
                        "unit": f"部队{i:03d}",
                        "location": f"区域{chr(65 + i % 26)}",
                        "strength": random.randint(50, 300),
                        "status": random.choice(["就绪", "行军", "战斗", "待命"])
                    }).encode('utf-8')
                    ioctx_warm.write_full(name, data)
                self._count_tiers()
                time.sleep(2)

                # ---- 步骤2: 模拟访问 ----
                self._step = 2
                hot_candidates = random.sample(obj_names, 10)
                warm_candidates = random.sample([n for n in obj_names if n not in hot_candidates], 20)
                cold_candidates = [n for n in obj_names if n not in hot_candidates and n not in warm_candidates]

                for name in hot_candidates:
                    self.record_access(name, count=random.randint(15, 25))
                for name in warm_candidates:
                    self.record_access(name, count=random.randint(3, 6))
                self.flush_access()
                time.sleep(2)

                # ---- 步骤3: 冷热识别迁移 ----
                self._step = 3
                for name in hot_candidates:
                    score = self.calculate_heat_score(name)
                    if score >= THRESHOLD_HOT:
                        self._promote_warm_to_hot(name, score=score)
                    time.sleep(0.05)
                demoted = []
                for name in cold_candidates:
                    score = self.calculate_heat_score(name)
                    if score < DEMOTE_WARM:
                        if self._demote_warm_to_cold(name, score=score):
                            demoted.append(name)
                    time.sleep(0.02)
                self._count_tiers()
                time.sleep(2)

                # ---- 步骤4: 冷数据备份（批量写入 Ceph backup_pool）----
                self._step = 4
                self._flush_snapshot_to_ceph()
                time.sleep(2)

                # ---- 步骤5: 回访回迁 ----
                self._step = 5
                revisit = random.sample(cold_candidates[:len(cold_candidates)//2], min(5, len(cold_candidates)//2))
                for name in revisit:
                    self.record_access(name, count=random.randint(8, 15))
                    score = self.calculate_heat_score(name)
                    if score >= THRESHOLD_WARM:
                        self._promote_cold_to_warm(name, score=score)
                    time.sleep(0.1)
                self.flush_access()
                self._count_tiers()
                time.sleep(2)

                # ---- 步骤6: 再次分层 ----
                self._step = 6
                for name in warm_candidates[:5]:
                    self.record_access(name, count=random.randint(12, 20))
                    score = self.calculate_heat_score(name)
                    if score >= THRESHOLD_HOT:
                        self._promote_warm_to_hot(name, score=score)
                    time.sleep(0.05)
                self.flush_access()
                self._count_tiers()
                time.sleep(1)

                self._step = 7  # 完成
            except Exception as e:
                print(f"Demo error: {e}")
                import traceback
                traceback.print_exc()
            finally:
                self._running = False
                self.flush_access()
                self._save_json(MIGRATION_FILE, self._migration_history)

        self._demo_thread = threading.Thread(target=demo_flow, daemon=True)
        self._demo_thread.start()
        return {"started": True}

    def get_status(self):
        """获取当前演示状态（演示运行中使用缓存的tier_state，避免反复遍历pool）"""
        if not self._running:
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
        """获取所有对象的详细信息(含层级和热度) - 缓存模式"""
        obj_map = {}
        self._ensure_hot_path()

        # 先收集所有对象名及其层级
        for f in os.listdir(HOT_PATH):
            if f.startswith('.'):
                continue
            obj_map[f] = {"name": f, "tier": "hot", "cache_layers": ["hot"]}

        try:
            for obj in self._get_warm_ioctx().list_objects():
                name = obj.key
                if name in obj_map:
                    obj_map[name]["cache_layers"].append("warm")
                else:
                    obj_map[name] = {"name": name, "tier": "warm", "cache_layers": ["warm"]}
        except:
            pass

        try:
            for obj in self._get_cold_ioctx().list_objects():
                name = obj.key
                if name in obj_map:
                    obj_map[name]["cache_layers"].append("cold")
                else:
                    obj_map[name] = {"name": name, "tier": "cold", "cache_layers": ["cold"]}
        except:
            pass

        # 统一计算一次热度分数
        for name, info in obj_map.items():
            info["heat_score"] = round(self.calculate_heat_score(name), 2)

        return list(obj_map.values())

    def reset(self):
        """重置演示"""
        if self._running:
            self._running = False
            time.sleep(2)
        self._step = 0
        self._migration_events = []
        self._snapshot_events = []
        self._pending_snapshot_objs = []
        self._clean_all_tiers()
        return {"ok": True}


if USE_MOCK:
    tiering_module = MockTieringModule()
    print("[M6] Mock 模式已启用")
else:
    tiering_module = TieringModule()

# ============================================================
# M6 Blueprint
# ============================================================

m6_bp = Blueprint('m6', __name__)


@m6_bp.route('/api/m6/start', methods=['POST'])
def m6_start():
    try:
        result = tiering_module.start_demo()
        return jsonify({"ok": True, **result})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@m6_bp.route('/api/m6/status', methods=['GET'])
def m6_status():
    try:
        status = tiering_module.get_status()
        return jsonify({"ok": True, **status})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@m6_bp.route('/api/m6/objects', methods=['GET'])
def m6_objects():
    try:
        details = tiering_module.get_object_details()
        return jsonify({"ok": True, "objects": details})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@m6_bp.route('/api/m6/reset', methods=['POST'])
def m6_reset():
    try:
        result = tiering_module.reset()
        return jsonify(result)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@m6_bp.route("/api/m6/snapshot/<name>", methods=["GET"])
def m6_snapshot_detail(name):
    """获取快照详情 — 读取快照记录文件"""
    if USE_MOCK:
        # Mock 模式下从内存中的 snapshot_events 返回摘要
        for snap in tiering_module._snapshot_events:
            if snap.get("name") == name:
                return jsonify({
                    "ok": True,
                    "name": name,
                    "timestamp": snap.get("ts", ""),
                    "count": snap.get("count", 0),
                    "objects": [],
                })
        return jsonify({"ok": False, "error": "快照不存在"}), 404
    try:
        snap_file = os.path.join(TIERING_DATA_DIR, f"{name}.json")
        if not os.path.exists(snap_file):
            return jsonify({"ok": False, "error": "快照文件不存在"}), 404
        with open(snap_file, 'r') as f:
            data = json.load(f)
        objects = []
        for obj_name, info in data.get("objects", {}).items():
            objects.append({
                "name": obj_name,
                "size": info.get("size", 0),
                "hash": info.get("hash", "--------"),
            })
        objects.sort(key=lambda x: x["name"])
        return jsonify({
            "ok": True,
            "name": data.get("name", name),
            "timestamp": data.get("timestamp", ""),
            "count": len(objects),
            "objects": objects,
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@m6_bp.route('/api/m6/stream', methods=['GET'])
def m6_stream():
    """M6分级存储的SSE实时推送"""
    def generate():
        last_step = -1
        last_mig_count = 0
        last_snap_count = 0
        while True:
            status = tiering_module.get_status()
            step = status["step"]
            mig_count = len(status["migration_events"])
            snap_count = len(status["snapshot_events"])

            if step != last_step or mig_count != last_mig_count or snap_count != last_snap_count:
                payload = json.dumps(status)
                yield f"data: {payload}\n\n"
                last_step = step
                last_mig_count = mig_count
                last_snap_count = snap_count

            if not status["running"] and step > 0:
                yield f"data: {json.dumps({'done': True, **status})}\n\n"
                break
            time.sleep(1.0)

    return Response(generate(), mimetype='text/event-stream')
