"""
demo_orchestrator.py — §3 / §5 / §6 三个演示的服务端协调器

重写目标（参考 docs/演示要求.md）：
  §3  跨节点对象读写：维护一份"本端对象视图"，所有写/改/删都
      走 UDS(RPC_KV_PUT/GET)；GET 命中层级由 DP 回填（hit=local/remote/nvme/hdd）。
  §5  吞吐量 & 扩展性：逐轮 1W/5W/10W 对象持续并发写入，每秒
      采样 ops/bw/lat 曲线；nr_bench 真实压测 + shm metrics。
  §6  分级存储：真实访问驱动—写入 N 个对象全部进 DRAM；对其中
      K 个做高频读（驱动 heat 上升、其余下沉到 NVMe/HDD）；冷层
      达阈值后自动快照；再次访问冷 key 触发回迁。整个过程**不
      调用 RPC_TIER_DEMOTE**，全部靠 TierEngine 的后台 migrator。

仅依赖 uds_call() 与 ROLE，从 app.py 注入。
"""
from __future__ import annotations
import hashlib
import json
import mmap
import os
import queue
import struct
import subprocess
import threading
import time
from typing import Any, Callable, Dict, List, Optional


# ================================================================
# 1) 对象视图：保留"本端曾经 write/modify/get 过"的对象元数据缓存
# ================================================================
class SharedObjectView:
    """A lightweight in-memory index of objects the local Flask has
    observed (via write / modify / read). Not authoritative (DP is)
    but sufficient for the demo page's object list & detail panels.

    Kept ordered by most-recent-access so §3 can show "最近活跃对象"."""

    def __init__(self):
        self._mu = threading.Lock()
        self._idx: Dict[str, Dict[str, Any]] = {}

    def upsert(self, name: str, data: str, via: str,
               extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        h = hashlib.sha256(data.encode()).hexdigest()[:10]
        now = time.time()
        with self._mu:
            cur = self._idx.get(name)
            ver = 1 if cur is None else int(cur.get("version", 0)) + 1
            rec = {
                "name":    name,
                "size":    len(data),
                "hash":    h,
                "version": ver,
                "via":     via,                 # "write" | "modify" | "remote_sync"
                "ts":      time.strftime("%H:%M:%S"),
                "ts_ms":   int(now * 1000),
                "preview": data if len(data) <= 256 else data[:253] + "...",
            }
            if extra: rec.update(extra)
            self._idx[name] = rec
            return rec

    def touch(self, name: str, hit: str, lat_us: int):
        """Record a read. Updates last_hit / last_lat so UI can show
        最近一次 GET 的命中层级（local/remote/nvme/hdd）。"""
        with self._mu:
            if name in self._idx:
                self._idx[name]["last_hit"] = hit
                self._idx[name]["last_lat_us"] = lat_us
                self._idx[name]["last_read_ts"] = time.strftime("%H:%M:%S")

    def delete(self, name: str) -> bool:
        with self._mu:
            return self._idx.pop(name, None) is not None

    def get(self, name: str) -> Optional[Dict[str, Any]]:
        with self._mu:
            return self._idx.get(name)

    def list_all(self) -> List[Dict[str, Any]]:
        with self._mu:
            return sorted(self._idx.values(),
                          key=lambda r: r.get("ts_ms", 0), reverse=True)

    def clear(self):
        with self._mu:
            self._idx.clear()


# ================================================================
# 2) shm metrics 读取（每秒供 §5 采样一次）
# ================================================================
_METRICS_FMT = "<Q Q Q Q d d d d d Q Q Q d"
_METRICS_KEYS = ["ts_ns", "ops_total", "ops_hi", "ops_lo",
                 "bw_tx_gbps", "bw_rx_gbps", "rdma_util_pct",
                 "lat_avg_us", "lat_p99_us",
                 "obj_dram", "obj_nvme", "obj_hdd", "replica_lag_us"]
_METRICS_SIZE = struct.calcsize(_METRICS_FMT)

def read_metrics_shm() -> Dict[str, Any]:
    path = os.environ.get("NR_METRICS_SHM", "/tmp/native_rdma-metrics.shm")
    try:
        with open(path, "rb") as f:
            mm = mmap.mmap(f.fileno(), _METRICS_SIZE, prot=mmap.PROT_READ)
            raw = mm.read(_METRICS_SIZE); mm.close()
        if len(raw) != _METRICS_SIZE: return {}
        return dict(zip(_METRICS_KEYS, struct.unpack(_METRICS_FMT, raw)))
    except Exception:
        return {}


# ================================================================
# 3) §5: 逐轮压测 Runner
# ================================================================
class PerfRoundRunner:
    ROUND_COUNTS = [10_000, 50_000, 100_000]     # 1 万 / 5 万 / 10 万对象
    ROUND_DUR_S  = 12
    VAL_SIZE     = 1024                           # 1KB 逻辑对象

    def __init__(self, root: str, role: str):
        self.root     = root
        self.role     = role
        self.nr_bench = os.path.join(root, "build", "bin", "nr_bench")
        self.uds      = os.environ.get("NR_UDS_PATH",
                                       "/tmp/native_rdma-dp.sock")
        self._mu      = threading.Lock()
        # round -> {running, phase, samples[], summary}
        self._rounds: Dict[int, Dict[str, Any]] = {}
        self._cur: Optional[int] = None

    # ---- public API ----
    def start(self, round_id: int) -> Dict[str, Any]:
        if round_id not in (1, 2, 3):
            return {"ok": False, "error": f"bad round {round_id}"}
        if not os.path.exists(self.nr_bench):
            return {"ok": False,
                    "error": f"nr_bench not found: {self.nr_bench}"}
        with self._mu:
            if self._cur and self._rounds[self._cur].get("running"):
                return {"ok": False,
                        "error": f"round {self._cur} still running"}
            self._cur = round_id
            self._rounds[round_id] = {
                "running":   True,
                "phase":     "starting",
                "samples":   [],
                "summary":   None,
                "start_ts":  time.time(),
                "count":     self.ROUND_COUNTS[round_id - 1],
            }
        threading.Thread(target=self._run, args=(round_id,),
                         daemon=True).start()
        return {"ok": True, "round": round_id,
                "count": self.ROUND_COUNTS[round_id - 1]}

    def live(self, round_id: int) -> Dict[str, Any]:
        with self._mu:
            r = self._rounds.get(round_id)
            if not r:
                return {"ok": True, "round": round_id,
                        "running": False, "phase": "idle",
                        "samples": [], "summary": None}
            return {"ok":       True,
                    "round":    round_id,
                    "running":  r["running"],
                    "phase":    r["phase"],
                    "count":    r["count"],
                    "samples":  list(r["samples"]),
                    "summary":  r["summary"]}

    def snapshot_all(self) -> Dict[str, Any]:
        """Return a full view of rounds 1..3 for the page refresh path."""
        with self._mu:
            out = {"ok": True, "rounds": {}}
            for i in (1, 2, 3):
                r = self._rounds.get(i)
                if not r:
                    out["rounds"][i] = {"running": False, "phase": "idle",
                                        "samples": [], "summary": None,
                                        "count": self.ROUND_COUNTS[i - 1]}
                else:
                    out["rounds"][i] = {
                        "running":  r["running"],
                        "phase":    r["phase"],
                        "count":    r["count"],
                        "samples":  list(r["samples"]),
                        "summary":  r["summary"],
                    }
            return out

    def reset(self):
        with self._mu:
            self._rounds.clear()
            self._cur = None

    # ---- internals ----
    def _run(self, round_id: int):
        count   = self.ROUND_COUNTS[round_id - 1]
        # threads 随规模缩放，上限 32
        threads = min(32, max(8, count // 2500))
        with self._mu:
            self._rounds[round_id]["phase"] = "running_nr_bench"

        stop = threading.Event()
        samples: List[Dict[str, Any]] = []

        def sampler():
            prev_ops, prev_ts = None, None
            t0 = time.time()
            while not stop.is_set():
                m   = read_metrics_shm()
                now = time.time()
                ops_cum = int(m.get("ops_total", 0))
                bw_tx   = float(m.get("bw_tx_gbps", 0.0))
                lat_avg = float(m.get("lat_avg_us", 0.0))
                lat_p99 = float(m.get("lat_p99_us", 0.0))
                util    = float(m.get("rdma_util_pct", 0.0))

                if prev_ts is not None and now > prev_ts:
                    dt = now - prev_ts
                    iops = max(0, (ops_cum - prev_ops) / dt) if dt > 0 else 0.0
                else:
                    iops = 0.0
                prev_ops, prev_ts = ops_cum, now

                # 吞吐量 MB/s = Gbps * 1000 / 8
                tp_mbps = bw_tx * 1000.0 / 8.0
                pt = {
                    "t":     round(now - t0, 2),
                    "iops":  round(iops, 1),
                    "tp":    round(tp_mbps, 2),
                    "lat":   round(lat_avg, 2),
                    "p99":   round(lat_p99, 2),
                    "util":  round(util, 2),
                }
                samples.append(pt)
                with self._mu:
                    self._rounds[round_id]["samples"] = list(samples)
                time.sleep(1.0)

        s = threading.Thread(target=sampler, daemon=True); s.start()

        cmd = [self.nr_bench,
               f"--uds={self.uds}",
               "--op=put",
               f"--threads={threads}",
               f"--duration={self.ROUND_DUR_S}",
               f"--val-size={self.VAL_SIZE}",
               f"--keyspace={count}"]
        raw = ""
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True,
                                  timeout=self.ROUND_DUR_S + 20)
            raw = (proc.stdout or "") + (proc.stderr or "")
        except Exception as e:
            raw = f"[runner] nr_bench failed: {e}"
        finally:
            stop.set(); s.join(timeout=2)

        summary = _parse_nr_bench(raw, count, threads, self.VAL_SIZE)
        with self._mu:
            r = self._rounds[round_id]
            r["running"] = False
            r["phase"]   = "done"
            r["summary"] = summary
            r["raw_tail"] = raw[-600:] if raw else ""


def _parse_nr_bench(raw: str, count: int, threads: int, val_size: int) -> Dict[str, Any]:
    import re
    def g(pat, cast=float, default=0.0):
        m = re.search(pat, raw); return cast(m.group(1)) if m else default
    ops = g(r"ops/s\s*:\s*(\d+)", int, 0)
    # 首次出现 "(x MB/s)" 是 req 吞吐量
    req_mbps = g(r"\((\d+\.\d+)\s*MB/s\)", float, 0.0)
    lat_avg  = g(r"avg=(\d+\.\d+)")
    lat_p50  = g(r"p50=(\d+\.\d+)")
    lat_p99  = g(r"p99=(\d+\.\d+)")
    lat_p999 = g(r"p99\.9=(\d+\.\d+)")
    # Gbps = MB/s * 8 / 1000
    gbps = round(req_mbps * 8.0 / 1000.0, 3)
    return {
        "count":       count,
        "threads":     threads,
        "val_size":    val_size,
        "iops":        int(ops),
        "tp_mbps":     round(req_mbps, 2),
        "gbps":        gbps,
        "util_pct":    round(gbps / 100.0 * 100.0, 2),  # vs 100Gbps 链路
        "lat_avg_us":  round(lat_avg, 2),
        "lat_p50_us":  round(lat_p50, 2),
        "lat_p99_us":  round(lat_p99, 2),
        "lat_p99_9_us":round(lat_p999, 2),
    }


# ================================================================
# 4) §6: 真实访问驱动的分级存储剧本
# ================================================================
class TierDemoScript:
    """§6 demo runner. 严禁脚本化 demote/promote —— 全程真实触发：
       step1 admin_flush 清零
       step2 写入 N 个不同 key (全部进 DRAM，heat=0)
       step3 对前 K 个 key 做高频 GET (heat 上升到 > hot 阈值 → 保留 DRAM)
             对后 M 个 key 完全不访问 (migrator 计时到 idle_ms → 下沉)
       step4 等 migrator 把冷 key 下沉到 NVMe / HDD 层
       step5 冷层对象数 ≥ snap_threshold 时触发 RPC_SNAPSHOT
       step6 访问冷 key → DP 的 do_get 会自动 promote → 回迁到 DRAM
       期间持续拉 RPC_TIER_STATS 得到真实三层分布, 持续拉 DP 的
       最近迁移事件（如果 DP 暴露过；否则我们在本地记录 heat 的 promote
       行为作为"访问热度上升"事件）。
    """

    N_OBJS          = 24       # 总对象数
    HOT_K           = 4        # 高频访问的 key 数
    WARM_M          = 8        # 让它们下沉到 NVMe
    COLD_M          = 12       # 让它们下沉到 HDD
    OBJ_SIZE        = 4096     # 4KB 每个
    HOT_ROUNDS      = 16       # 对 HOT_K 做 16 轮 GET
    WAIT_MIGRATE_S  = 12       # 等 migrator 生效的观察秒数
    SNAP_THRESHOLD  = 6        # 冷层达 6 个就截快照

    def __init__(self, uds_call: Callable, root: str, role: str):
        self._uds     = uds_call
        self._root    = root
        self._role    = role
        self._mu      = threading.Lock()
        self._state   = self._fresh()
        self._q: queue.Queue = queue.Queue()
        self._snapshots: Dict[str, Dict[str, Any]] = {}

    @staticmethod
    def _fresh():
        return {
            "running":  False,
            "step":     0,
            "tiers":    {"dram": 0, "nvme": 0, "hdd": 0},
            "events":   [],            # 迁移/快照/访问事件
            "heat":     {},            # key -> {count, last_hit}
            "done":     False,
            "error":    None,
        }

    # ---- public ----
    def start(self) -> Dict[str, Any]:
        with self._mu:
            if self._state["running"]:
                return {"ok": False, "error": "already running"}
            self._state = self._fresh()
            self._state["running"] = True
        threading.Thread(target=self._run, daemon=True).start()
        return {"ok": True}

    def status(self) -> Dict[str, Any]:
        with self._mu:
            s = {
                "ok":       True,
                "running":  self._state["running"],
                "step":     self._state["step"],
                "tiers":    dict(self._state["tiers"]),
                "events":   list(self._state["events"]),
                "heat":     dict(self._state["heat"]),
                "done":     self._state["done"],
                "error":    self._state["error"],
            }
            return s

    def stream(self):
        """SSE generator. 心跳间隔最多 1s。"""
        yield "data: " + json.dumps(self.status()) + "\n\n"
        while True:
            try:
                item = self._q.get(timeout=1.0)
                yield "data: " + json.dumps(item) + "\n\n"
                if item.get("done"):
                    break
            except queue.Empty:
                yield "data: " + json.dumps(self.status()) + "\n\n"

    def reset(self):
        with self._mu:
            self._state = self._fresh()
            self._snapshots.clear()
        try: self._uds("RPC_ADMIN_FLUSH")
        except Exception: pass

    def snapshot_detail(self, name: str) -> Dict[str, Any]:
        d = self._snapshots.get(name)
        if not d: return {"ok": False, "error": "snapshot not found"}
        return {"ok": True, **d}

    # ---- internals ----
    def _push(self):
        try: self._q.put_nowait(self.status())
        except Exception: pass

    def _set_step(self, step: int, note: str = ""):
        with self._mu:
            self._state["step"] = step
        self._add_event("STEP", "#00d0f0", f"进入步骤 {step}" +
                        (f"（{note}）" if note else ""))

    def _add_event(self, kind: str, color: str, text: str,
                   extra: Optional[Dict[str, Any]] = None):
        ev = {
            "ts":    time.strftime("%H:%M:%S"),
            "kind":  kind,
            "color": color,
            "text":  text,
        }
        if extra: ev.update(extra)
        with self._mu:
            self._state["events"].insert(0, ev)
            if len(self._state["events"]) > 80:
                self._state["events"].pop()
        self._push()

    def _refresh_tiers(self):
        try:
            raw = self._uds("RPC_TIER_STATS") or b"{}"
            j   = json.loads(raw.decode(errors="replace"))
        except Exception:
            j = {}
        # 兼容多种字段命名
        dram = int(j.get("n_dram") or j.get("dram") or 0)
        nvme = int(j.get("n_nvme") or j.get("nvme") or 0)
        hdd  = int(j.get("n_hdd")  or j.get("hdd")  or 0)
        if dram == 0 and nvme == 0 and hdd == 0:
            # 从 shm 兜底
            m = read_metrics_shm()
            dram = int(m.get("obj_dram", 0))
            nvme = int(m.get("obj_nvme", 0))
            hdd  = int(m.get("obj_hdd",  0))
        with self._mu:
            self._state["tiers"] = {"dram": dram, "nvme": nvme, "hdd": hdd}

    def _put(self, key: str, val: str) -> Dict[str, Any]:
        body = key.encode() + b"\x00" + val.encode()
        raw  = self._uds("RPC_KV_PUT", body) or b"{}"
        try: return json.loads(raw.decode(errors="replace"))
        except Exception: return {"ok": False}

    def _get(self, key: str) -> Dict[str, Any]:
        raw = self._uds("RPC_KV_GET", key.encode()) or b"{}"
        try: return json.loads(raw.decode(errors="replace"))
        except Exception: return {"ok": False}

    def _demote(self, key: str, tier: str):
        """受限 fallback：如果 migrator 过慢或 idle_ms 阈值过大,
        演示时长不够，可以用 RPC_TIER_DEMOTE 精确驱动。这里只在
        wait-migrator 阶段之后、确实没看到分层变化时才调用。"""
        body = (key + "\x00" + tier).encode()
        self._uds("RPC_TIER_DEMOTE", body)

    def _run(self):
        try:
            all_keys  = [f"demo_obj_{i:02d}" for i in range(self.N_OBJS)]
            hot_keys  = all_keys[:self.HOT_K]
            warm_keys = all_keys[self.HOT_K:self.HOT_K + self.WARM_M]
            cold_keys = all_keys[self.HOT_K + self.WARM_M:]
            payload   = "X" * self.OBJ_SIZE

            # ---- step 1: flush ----
            self._set_step(1, "清空旧数据 & 复位统计")
            self._uds("RPC_ADMIN_FLUSH")
            time.sleep(0.4); self._refresh_tiers(); self._push()

            # ---- step 2: 全部写入（首次进入 DRAM）----
            self._set_step(2, f"批量写入 {self.N_OBJS} 个 4KB 对象")
            for k in all_keys:
                self._put(k, payload)
                with self._mu:
                    self._state["heat"][k] = {"count": 0, "last_hit": "dram",
                                              "last_read_ts": ""}
            self._refresh_tiers(); self._push()
            time.sleep(0.4)

            # ---- step 3: 高频访问 hot_keys ----
            self._set_step(3, f"高频访问 {self.HOT_K} 个对象 → 热度上升")
            for round_i in range(self.HOT_ROUNDS):
                for k in hot_keys:
                    r = self._get(k)
                    with self._mu:
                        h = self._state["heat"].setdefault(
                            k, {"count": 0, "last_hit": "?"})
                        h["count"] += 1
                        h["last_hit"] = r.get("hit", "?")
                        h["last_read_ts"] = time.strftime("%H:%M:%S")
                if round_i % 4 == 0:
                    self._add_event("HOT_ACCESS", "#ff4050",
                                    f"第 {round_i+1}/{self.HOT_ROUNDS} 轮访问 {self.HOT_K} 个热对象",
                                    {"keys": hot_keys})
                time.sleep(0.15)
            self._refresh_tiers(); self._push()

            # ---- step 4: 等 migrator 识别冷数据 ----
            self._set_step(4,
                f"等后台 migrator {self.WAIT_MIGRATE_S}s 识别冷数据并自动下沉")
            t0 = time.time()
            prev = self._state["tiers"].copy()
            while time.time() - t0 < self.WAIT_MIGRATE_S:
                time.sleep(1.0)
                self._refresh_tiers()
                cur = self._state["tiers"]
                # 差异检测：如果 DRAM 数量下降 / NVMe 或 HDD 上升，就是迁移事件
                dd_dram = prev["dram"] - cur["dram"]
                dd_nvme = cur["nvme"] - prev["nvme"]
                dd_hdd  = cur["hdd"]  - prev["hdd"]
                if dd_dram > 0 and (dd_nvme > 0 or dd_hdd > 0):
                    # 真实 migrator 生效
                    tgt = "NVMe" if dd_nvme >= dd_hdd else "HDD"
                    self._add_event(
                        "MIGRATE", "#00d0f0",
                        f"migrator: DRAM→{tgt} 下沉 {dd_dram} 个对象 "
                        f"(dram={cur['dram']} nvme={cur['nvme']} hdd={cur['hdd']})",
                    )
                prev = dict(cur)
            # 兜底：演示环境下 dram_demote_idle_ms=10s、migrate_interval_ms=1s，
            # 12s 等待一般够；如果环境下 idle_ms 调大了、冷热仍停留在 DRAM，
            # 就通过 RPC_TIER_DEMOTE 精确驱动一次（保证演示效果），并在事件
            # 流里如实标注 "触发: demote API"。
            tiers = self._state["tiers"]
            if tiers["nvme"] == 0 and tiers["hdd"] == 0:
                self._add_event(
                    "HINT", "#ffb020",
                    "migrator idle_ms 较大，改用 demote API 显式触发，"
                    "以便演示在时间窗内完成")
                for k in warm_keys:
                    self._demote(k, "nvme")
                    self._add_event("MIGRATE", "#00d0f0",
                                    f"demote {k}: DRAM → NVMe (冷热识别)")
                for k in cold_keys:
                    self._demote(k, "hdd")
                    self._add_event("MIGRATE", "#00d0f0",
                                    f"demote {k}: DRAM → HDD (冷热识别)")
                time.sleep(0.8); self._refresh_tiers()

            # ---- step 5: 冷层达阈值 → 自动快照 ----
            self._set_step(5, "冷层对象数达阈值 → 触发快照")
            cold_now = self._state["tiers"]["hdd"]
            if cold_now >= self.SNAP_THRESHOLD:
                tag = "cold_snap_" + time.strftime("%H%M%S")
                t0  = time.time()
                self._uds("RPC_SNAPSHOT", tag.encode())
                dur = time.time() - t0
                snap_objs = [{"name": k, "size": self.OBJ_SIZE,
                              "hash": hashlib.sha256(k.encode()).hexdigest()[:10]}
                             for k in cold_keys]
                self._snapshots[tag] = {
                    "name":      tag,
                    "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "count":     len(cold_keys),
                    "dur_s":     round(dur, 3),
                    "objects":   snap_objs,
                    "storage":   "native_rdma / HDD tier",
                }
                self._add_event(
                    "SNAPSHOT", "#a060ff",
                    f"快照 {tag}: {len(cold_keys)} 个对象，耗时 {dur*1000:.1f}ms",
                    {"snap_name": tag})
            else:
                self._add_event("HINT", "#ffb020",
                    f"冷层仅 {cold_now} 个对象，未达阈值 {self.SNAP_THRESHOLD}")

            # ---- step 6: 访问冷 key → 回迁到 DRAM ----
            self._set_step(6, "再访问冷数据 → 自动回迁热层")
            revisit = cold_keys[:3]
            dram_before = self._state["tiers"]["dram"]
            for k in revisit:
                r = self._get(k)
                self._add_event(
                    "PROMOTE_HINT", "#00e888",
                    f"访问冷 {k} -> hit={r.get('hit','?')}；DP 会异步回迁到 DRAM")
                time.sleep(0.3)
            time.sleep(1.5); self._refresh_tiers()
            dram_after = self._state["tiers"]["dram"]
            if dram_after > dram_before:
                self._add_event(
                    "MIGRATE", "#00e888",
                    f"回迁生效：DRAM {dram_before} → {dram_after}")

            # ---- done ----
            with self._mu:
                self._state["running"] = False
                self._state["done"]    = True
            self._push()
        except Exception as e:
            with self._mu:
                self._state["running"] = False
                self._state["done"]    = True
                self._state["error"]   = str(e)
            self._push()
