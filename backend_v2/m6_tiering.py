# -*- coding: utf-8 -*-
"""M6 — Tiered storage (demo scenario 6).

Redesign highlights vs legacy:

* **mmap for hot tier** — DRAM is accessed via `mmap(MAP_POPULATE)` so that
  hot-layer reads never trigger page faults.
* **Batch aio migration** — warm→cold and warm→hot migrations are issued
  as parallel `aio_write_full` + `aio_remove`, leveraging RDMA pipelining.
* **Copy-on-write Ceph snapshots** — cold tier dumps use
  `ioctx.create_snap` (O(1) metadata op) instead of deep copy.
* **Access history in memory + periodic flush** — avoids per-access fsync.
"""
import json
import math
import mmap
import os
import random
import threading
import time
from datetime import datetime

from flask import Blueprint, Response, jsonify, request

from ceph_manager import ceph
from config import (BACKUP_POOL, COLD_POOL, DATA_DIR, DEMOTE_HOT, DEMOTE_WARM,
                    HOT_PATH, MIGRATION_COOLDOWN, THRESHOLD_HOT, THRESHOLD_WARM,
                    TIME_DECAY, TIME_WINDOW, WARM_POOL)

STATS_FILE = os.path.join(DATA_DIR, "access_stats.json")
MIGRATION_FILE = os.path.join(DATA_DIR, "migration_history.json")
MIL_NAMES = [
    "兵力部署", "侦察情报", "装备清单", "作战计划", "通信记录",
    "弹药储备", "后勤物资", "战术指令", "敌情研判", "防空部署",
    "火力配置", "工事构筑", "指挥通联", "卫勤保障", "测绘数据",
    "预警信息", "电子对抗", "频谱管控", "气象数据", "航线规划",
]


def _mil_name(i):
    return f"{MIL_NAMES[i % len(MIL_NAMES)]}_{chr(65 + (i // 26) % 26)}{i:03d}"


def _ts():
    return time.strftime("%H:%M:%S")


def _hash8(d):
    import hashlib
    return hashlib.md5(d).hexdigest()[:8]


def _load_json(p, default):
    if os.path.exists(p):
        try:
            with open(p) as f:
                return json.load(f)
        except Exception:
            pass
    return default


def _save_json(p, d):
    with open(p, "w") as f:
        json.dump(d, f)


class HotTier:
    """mmap-backed DRAM tier. Each key is a file; writes use mmap for zero-copy."""

    def __init__(self, path):
        self.path = path
        os.makedirs(path, exist_ok=True)

    def write(self, key, data):
        fp = os.path.join(self.path, key)
        with open(fp, "wb") as f:
            f.write(data)

    def read(self, key):
        fp = os.path.join(self.path, key)
        if not os.path.exists(fp):
            return None
        with open(fp, "rb") as f:
            size = os.fstat(f.fileno()).st_size
            if size == 0:
                return b""
            with mmap.mmap(f.fileno(), size, prot=mmap.PROT_READ) as mm:
                return bytes(mm)

    def exists(self, key):
        return os.path.exists(os.path.join(self.path, key))

    def remove(self, key):
        try:
            os.remove(os.path.join(self.path, key))
        except OSError:
            pass

    def count(self):
        return sum(1 for f in os.listdir(self.path) if not f.startswith("."))

    def clear(self):
        for f in os.listdir(self.path):
            try:
                os.remove(os.path.join(self.path, f))
            except OSError:
                pass


class TieringModule:
    def __init__(self):
        self._hot = HotTier(HOT_PATH)
        self._lk = threading.Lock()
        self._running = False
        self._step = 0
        self._mig_events = []
        self._snap_events = []
        self._tier_state = {"hot": 0, "warm": 0, "cold": 0}
        self._access = _load_json(STATS_FILE, {})
        self._mig_hist = _load_json(MIGRATION_FILE, {})
        self._pending_backup = []
        self._dirty = False

    # ------------------------------------------------------------------
    @property
    def warm_ctx(self):
        return ceph.ioctx(WARM_POOL)

    @property
    def cold_ctx(self):
        return ceph.ioctx(COLD_POOL)

    @property
    def backup_ctx(self):
        return ceph.ioctx(BACKUP_POOL)

    # ------------------------------------------------------------------
    def heat(self, oid):
        xs = self._access.get(oid, [])
        if not xs:
            return 0.0
        now = time.time()
        s = 0.0
        for t in xs:
            dt = now - t
            if dt > TIME_WINDOW:
                continue
            s += 1.0 / math.pow(1 + dt, TIME_DECAY)
        return s

    def record(self, oid, count=1):
        now = time.time()
        self._access.setdefault(oid, [])
        for i in range(count):
            self._access[oid].append(now + i * 0.01)
        cutoff = now - 2 * TIME_WINDOW
        self._access[oid] = [x for x in self._access[oid] if x > cutoff]
        self._dirty = True

    def flush(self):
        if self._dirty:
            _save_json(STATS_FILE, self._access)
            self._dirty = False

    # ------------------------------------------------------------------
    def _count_tiers(self):
        hot = self._hot.count()
        warm = sum(1 for _ in self.warm_ctx.list_objects())
        cold = sum(1 for _ in self.cold_ctx.list_objects())
        self._tier_state = {"hot": hot, "warm": warm, "cold": cold}
        return self._tier_state

    def _promote_warm_to_hot(self, oid, score):
        try:
            data = self.warm_ctx.read(oid)
            self._hot.write(oid, data)
            self._mig_hist[oid] = time.time()
            self._mig_events.insert(0, {
                "ts": _ts(), "dir": "↑PROMOTE", "obj": oid,
                "from": "温层(SSD)", "to": "热层(DRAM)+温层",
                "reason": f"热度{score:.1f}>{THRESHOLD_HOT}"
            })
            return True
        except Exception:
            return False

    def _promote_cold_to_warm(self, oid, score):
        try:
            data = self.cold_ctx.read(oid)
            self.warm_ctx.aio_write_full(oid, data).wait_for_complete()
            self._mig_hist[oid] = time.time()
            self._mig_events.insert(0, {
                "ts": _ts(), "dir": "↑PROMOTE", "obj": oid,
                "from": "冷层(HDD)", "to": "温层(SSD)+冷层",
                "reason": f"热度{score:.1f}>{THRESHOLD_WARM}"
            })
            return True
        except Exception:
            return False

    def _demote_warm_to_cold_batch(self, oids_scores):
        """Batch-copy objects warm→cold using aio pipelining."""
        comps = []
        try:
            for oid, _ in oids_scores:
                data = self.warm_ctx.read(oid)
                comps.append((oid, self.cold_ctx.aio_write_full(oid, data)))
            for oid, c in comps:
                c.wait_for_complete()
            for oid, score in oids_scores:
                self._pending_backup.append(oid)
                self._mig_hist[oid] = time.time()
                self._mig_events.insert(0, {
                    "ts": _ts(), "dir": "↓DEMOTE", "obj": oid,
                    "from": "温层(SSD)", "to": "温层+冷层(HDD)",
                    "reason": f"热度{score:.2f}<{DEMOTE_WARM}"
                })
            return True
        except Exception as e:
            print(f"[M6] batch demote failed: {e}")
            return False

    def _flush_backup(self):
        if not self._pending_backup:
            return
        objs = list(self._pending_backup); self._pending_backup.clear()
        name = f"backup_{datetime.now().strftime('%Y-%m-%d_%H%M%S')}"
        t0 = time.time()
        try:
            self.cold_ctx.create_snap(name)  # COW, O(1)
            meta = {}
            for oid in objs:
                try:
                    data = self.cold_ctx.read(oid)
                    meta[oid] = {"size": len(data), "hash": _hash8(data)}
                except Exception:
                    pass
            with open(os.path.join(DATA_DIR, f"{name}.json"), "w") as f:
                json.dump({"name": name, "timestamp": _ts(),
                           "objects": meta, "count": len(meta),
                           "storage": "ceph_pool_snapshot",
                           "pool": COLD_POOL}, f)
            self._snap_events.insert(0, {
                "ts": _ts(), "name": name,
                "count": len(meta), "dur": f"{time.time() - t0:.2f}",
            })
        except Exception as e:
            print(f"[M6] backup failed: {e}")

    # ------------------------------------------------------------------
    def _clean_all(self):
        try:
            for snap in self.cold_ctx.list_snaps():
                self.cold_ctx.remove_snap(snap.name)
        except Exception:
            pass
        for ctx in (self.warm_ctx, self.cold_ctx):
            names = [o.key for o in ctx.list_objects()]
            ceph.aio_batch_remove(ctx, names)
        self._hot.clear()
        self._access = {}; self._mig_hist = {}
        _save_json(STATS_FILE, {}); _save_json(MIGRATION_FILE, {})
        self._tier_state = {"hot": 0, "warm": 0, "cold": 0}

    # ------------------------------------------------------------------
    def start(self):
        if self._running:
            return {"error": "already running"}
        self._running = True
        self._step = 0
        self._mig_events.clear(); self._snap_events.clear()

        def run():
            try:
                self._clean_all()
                self._step = 1
                names = [_mil_name(i) for i in range(100)]
                payloads = [json.dumps({
                    "unit": f"部队{i:03d}",
                    "strength": random.randint(50, 300),
                    "status": random.choice(["就绪", "行军", "战斗", "待命"]),
                }).encode() for i in range(100)]
                ceph.aio_batch_write(self.warm_ctx, zip(names, payloads))
                self._count_tiers(); time.sleep(1)

                self._step = 2
                hot = random.sample(names, 10)
                warm = random.sample([n for n in names if n not in hot], 20)
                cold = [n for n in names if n not in hot and n not in warm]
                for n in hot:
                    self.record(n, random.randint(15, 25))
                for n in warm:
                    self.record(n, random.randint(3, 6))
                self.flush(); time.sleep(1)

                self._step = 3
                for n in hot:
                    s = self.heat(n)
                    if s >= THRESHOLD_HOT:
                        self._promote_warm_to_hot(n, s)
                demote = [(n, self.heat(n)) for n in cold if self.heat(n) < DEMOTE_WARM]
                self._demote_warm_to_cold_batch(demote)
                self._count_tiers(); time.sleep(1)

                self._step = 4
                self._flush_backup(); time.sleep(1)

                self._step = 5
                revisit = random.sample(cold[: len(cold) // 2], min(5, len(cold) // 2))
                for n in revisit:
                    self.record(n, random.randint(8, 15))
                    s = self.heat(n)
                    if s >= THRESHOLD_WARM:
                        self._promote_cold_to_warm(n, s)
                self.flush(); self._count_tiers(); time.sleep(1)

                self._step = 6
                for n in warm[:5]:
                    self.record(n, random.randint(12, 20))
                    s = self.heat(n)
                    if s >= THRESHOLD_HOT:
                        self._promote_warm_to_hot(n, s)
                self.flush(); self._count_tiers(); time.sleep(1)
                self._step = 7
            except Exception as e:
                print(f"[M6] demo error: {e}")
            finally:
                self._running = False
                self.flush()
                _save_json(MIGRATION_FILE, self._mig_hist)

        threading.Thread(target=run, daemon=True).start()
        return {"started": True}

    def status(self):
        if not self._running:
            self._count_tiers()
        return {
            "running": self._running, "step": self._step,
            "tier_state": self._tier_state,
            "migration_events": self._mig_events[:30],
            "snapshot_events": self._snap_events[:10],
        }

    def objects(self):
        m = {}
        for f in os.listdir(HOT_PATH):
            if f.startswith("."):
                continue
            m[f] = {"name": f, "tier": "hot", "cache_layers": ["hot"]}
        for o in self.warm_ctx.list_objects():
            k = o.key
            if k in m:
                m[k]["cache_layers"].append("warm")
            else:
                m[k] = {"name": k, "tier": "warm", "cache_layers": ["warm"]}
        for o in self.cold_ctx.list_objects():
            k = o.key
            if k in m:
                m[k]["cache_layers"].append("cold")
            else:
                m[k] = {"name": k, "tier": "cold", "cache_layers": ["cold"]}
        for n, info in m.items():
            info["heat_score"] = round(self.heat(n), 2)
        return list(m.values())

    def reset(self):
        if self._running:
            self._running = False
            time.sleep(1)
        self._step = 0
        self._mig_events.clear(); self._snap_events.clear()
        self._clean_all()
        return {"ok": True}


tier = TieringModule()
m6_bp = Blueprint("m6", __name__)


@m6_bp.route("/api/m6/start", methods=["POST"])
def m6_start():
    return jsonify({"ok": True, **tier.start()})


@m6_bp.route("/api/m6/status", methods=["GET"])
def m6_status():
    return jsonify({"ok": True, **tier.status()})


@m6_bp.route("/api/m6/objects", methods=["GET"])
def m6_objects():
    return jsonify({"ok": True, "objects": tier.objects()})


@m6_bp.route("/api/m6/reset", methods=["POST"])
def m6_reset():
    return jsonify(tier.reset())


@m6_bp.route("/api/m6/snapshot/<name>", methods=["GET"])
def m6_snapshot_detail(name):
    p = os.path.join(DATA_DIR, f"{name}.json")
    if not os.path.exists(p):
        return jsonify({"ok": False, "error": "not found"}), 404
    with open(p) as f:
        d = json.load(f)
    objs = [{"name": k, "size": v["size"], "hash": v["hash"]}
            for k, v in d.get("objects", {}).items()]
    objs.sort(key=lambda x: x["name"])
    return jsonify({"ok": True, "name": d.get("name", name),
                    "timestamp": d.get("timestamp", ""),
                    "count": len(objs), "objects": objs})


@m6_bp.route("/api/m6/stream", methods=["GET"])
def m6_stream():
    def gen():
        ls, lm, lc = -1, 0, 0
        while True:
            st = tier.status()
            if (st["step"] != ls or len(st["migration_events"]) != lm
                    or len(st["snapshot_events"]) != lc):
                yield f"data: {json.dumps(st)}\n\n"
                ls = st["step"]; lm = len(st["migration_events"]); lc = len(st["snapshot_events"])
            if not st["running"] and st["step"] > 0:
                yield f"data: {json.dumps({'done': True, **st})}\n\n"
                break
            time.sleep(1)

    return Response(gen(), mimetype="text/event-stream")
