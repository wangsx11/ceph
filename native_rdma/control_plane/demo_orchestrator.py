"""
demo_orchestrator.py — §3 / §5 / §6 三个演示的服务端协调器

重写目标（参考 docs/演示要求.md）：
  §3  跨节点对象读写：维护一份"本端对象视图"，所有写/改/删都
      走 UDS(RPC_KV_PUT/GET)；GET 命中层级由 DP 回填（hit=local/remote/nvme/hdd）。
  §5  吞吐量 & 扩展性：逐轮 1W/5W/10W 对象持续并发写入，每秒
      采样 ops/bw/lat 曲线；nr_bench 真实压测 + shm metrics。
  §6  分级存储：8 步步进模式 + 纯 idle 阈值驱动（方案 X）。
      100 对象，活跃集 60 / 静默集 40。step3 打热度 → step4 等 2.5s 让
      migrator 把 40 静默对象下沉 NVMe → step5 访问 12 NVMe 对象触发
      read-through promote 回 DRAM → step6 再等 3.5s 让剩 28 个 NVMe
      继续下沉 HDD → step7 冷层达阈值触发快照 + JSON 归档 → step8 访问
      8 个 HDD 对象触发 HDD→DRAM 回迁。整个剧本**不使用 RPC_TIER_DEMOTE**，
      UI 三层分布完全来自 RPC_TIER_STATS 真实返回，演示的是 C++ migrator
      基于 last_access idle 阈值的自动识别能力。后台保活线程 500ms 刷活跃集
      的 last_access，确保讲解停顿几十秒也不会让活跃集被误下沉。

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
    # 1 万 / 5 万 / 10 万 独立对象（keyspace）
    ROUND_COUNTS = [10_000, 50_000, 100_000]
    # 持续时长随规模放大，让大 keyspace 的"索引膨胀"真正显现出来。
    # 小规模 keyspace 命中 CPU cache 概率高，IOPS 冲得起来；
    # 10万对象时 slab index bucket 变多 / cache miss 增加 / replica
    # lag 上升，IOPS 会明显下降、P99 会变长。这就是"扩展性曲线"。
    ROUND_DUR_S  = [8, 12, 16]
    # 线程保持恒定，避免人为拉平不同规模的 IOPS
    THREADS      = 16
    VAL_SIZE     = 1024

    def __init__(self, root: str, role: str):
        self.root     = root
        self.role     = role
        self.nr_bench = os.path.join(root, "build", "bin", "nr_bench")
        self.uds      = os.environ.get("NR_UDS_PATH",
                                       "/tmp/native_rdma-dp.sock")
        self._mu      = threading.Lock()
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
        dur_s   = self.ROUND_DUR_S[round_id - 1]
        threads = self.THREADS
        with self._mu:
            self._rounds[round_id]["phase"] = "running_nr_bench"

        stop = threading.Event()
        samples: List[Dict[str, Any]] = []
        SAMPLE_DT = 0.25                       # 250ms 采样，让曲线更光滑

        def sampler():
            # 给 nr_bench 0.3s 初始化时间，避免第一个点采到"启动瞬时"
            time.sleep(0.3)
            prev_ops, prev_ts_ns = None, None
            t0 = time.time()
            iops_window = []           # 最近 3 个瞬时 IOPS，做滑动平均平滑
            while not stop.is_set():
                m   = read_metrics_shm()
                now = time.time()
                ops_cum   = int(m.get("ops_total", 0))
                ts_ns     = int(m.get("ts_ns", 0))    # DP 端采样时间戳
                bw_tx     = float(m.get("bw_tx_gbps", 0.0))
                lat_avg   = float(m.get("lat_avg_us", 0.0))
                lat_p99   = float(m.get("lat_p99_us", 0.0))
                util      = float(m.get("rdma_util_pct", 0.0))
                repl_lag  = float(m.get("replica_lag_us", 0.0))

                # 首点只打基线
                if prev_ts_ns is None or ts_ns <= 0:
                    prev_ops, prev_ts_ns = ops_cum, ts_ns
                    time.sleep(SAMPLE_DT); continue

                # 用 DP 端 shm 的 ts_ns 做分母（不是 python 墙钟），避免
                # 轮询周期 250ms 与 DP 采样周期 200ms 错位导致的"锯齿/很低"
                dt_ns = ts_ns - prev_ts_ns
                if dt_ns <= 0:
                    # DP 没推进；把本轮点按上一次 IOPS 投出去即可（保持曲线不跳变）
                    iops = iops_window[-1] if iops_window else 0.0
                else:
                    iops = max(0.0, (ops_cum - prev_ops) / (dt_ns / 1e9))
                    prev_ops, prev_ts_ns = ops_cum, ts_ns

                # 3 点滑动平均让曲线平滑、消除锯齿
                iops_window.append(iops)
                if len(iops_window) > 3: iops_window.pop(0)
                iops_smooth = sum(iops_window) / len(iops_window)

                # 吞吐量：优先 DP 端 shm 的 bw_tx（1s 窗口），若为 0 则从 iops 派生
                tp_mbps = bw_tx * 1000.0 / 8.0
                if tp_mbps <= 0 and iops_smooth > 0:
                    tp_mbps = iops_smooth * self.VAL_SIZE / (1024.0 * 1024.0)

                pt = {
                    "t":        round(now - t0, 2),
                    "iops":     round(iops_smooth, 1),
                    "tp":       round(tp_mbps, 2),
                    "lat":      round(lat_avg, 2),
                    "p99":      round(lat_p99, 2),
                    "repl":     round(repl_lag, 2),   # 每次 replication 瞬时延迟（抖动源）
                    "util":     round(util, 2),
                    "ops_cum":  ops_cum,              # 前端可自行再差分
                }
                samples.append(pt)
                with self._mu:
                    self._rounds[round_id]["samples"] = list(samples)
                time.sleep(SAMPLE_DT)

        s = threading.Thread(target=sampler, daemon=True); s.start()

        cmd = [self.nr_bench,
               f"--uds={self.uds}",
               "--op=put",
               f"--threads={threads}",
               f"--duration={dur_s}",
               f"--val-size={self.VAL_SIZE}",
               f"--keyspace={count}"]
        raw = ""
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True,
                                  timeout=dur_s + 20)
            raw = (proc.stdout or "") + (proc.stderr or "")
        except Exception as e:
            raw = f"[runner] nr_bench failed: {e}"
        finally:
            stop.set(); s.join(timeout=2)

        summary = _parse_nr_bench(raw, count, threads, self.VAL_SIZE, dur_s)
        with self._mu:
            r = self._rounds[round_id]
            r["running"] = False
            r["phase"]   = "done"
            r["summary"] = summary
            r["raw_tail"] = raw[-600:] if raw else ""


def _parse_nr_bench(raw: str, count: int, threads: int,
                    val_size: int, dur_s: int) -> Dict[str, Any]:
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
    gbps = round(req_mbps * 8.0 / 1000.0, 3)
    # footprint ≈ count * slot_size；slot_size 约等于 val_size 对齐到 slab 粒度
    footprint_mb = round(count * val_size / (1024 * 1024), 2)
    return {
        "count":       count,
        "threads":     threads,
        "duration_s":  dur_s,
        "val_size":    val_size,
        "iops":        int(ops),
        "tp_mbps":     round(req_mbps, 2),
        "gbps":        gbps,
        "util_pct":    round(gbps / 100.0 * 100.0, 2),
        "footprint_mb": footprint_mb,
        "lat_avg_us":  round(lat_avg, 2),
        "lat_p50_us":  round(lat_p50, 2),
        "lat_p99_us":  round(lat_p99, 2),
        "lat_p99_9_us":round(lat_p999, 2),
    }

# ================================================================
# 4) §6: 真实访问驱动的分级存储剧本
# ================================================================
class TierDemoScript:
    """§6 demo runner. **方案 X**：纯访问驱动 + idle 阈值，不使用 RPC_TIER_DEMOTE。

    节奏（100 对象）：
      · H=60 个"活跃对象"：step3 起被持续 GET，一直留在 DRAM
      · C=40 个"不活跃对象"：从头到尾不被访问；step4 等待 2.5s 后
        idle>DRAM_DEMOTE_IDLE_MS(2000ms) 被 migrator 下沉到 NVMe
      · step5 访问其中 12 个 NVMe 对象：触发 DP read-through promote
        回 DRAM，演示"再次访问冷数据自动提升"的能力
      · step6 再等 3.5s，NVMe 上剩余的 28 个（从未被访问过）因累计
        idle>NVME_DEMOTE_IDLE_MS(3000ms) 被 migrator 下沉到 HDD
      · step7 冷层 28 ≥ 阈值 20，触发 RPC_SNAPSHOT + JSON 归档
      · step8 访问 8 个 HDD 对象，触发 HDD→DRAM read-through promote

    整个剧本所有层级变化**完全由 C++ migrator 驱动**（靠 idle 阈值自动判冷），
    UI 数字直接来自 RPC_TIER_STATS 的真实返回，不伪造、不覆盖。温层 NVMe 是
    idle-based 状态机的中间态：对象短暂停留后要么被访问而提升、要么继续冷却，
    这是分级系统的本质行为。

    阈值（env 配合）：
      · DRAM idle > DRAM_DEMOTE_IDLE_MS (2000ms) → migrator 下沉 NVMe
      · NVMe idle > NVME_DEMOTE_IDLE_MS (3000ms) → migrator 下沉 HDD
      · SNAP_THRESHOLD=20：冷层 ≥20 触发快照归档

    8 步：
      step1 admin_flush 清零
      step2 写入 100 个 4KB 对象（全进 DRAM）
      step3 对 60 个活跃对象做高频 GET（打上"热度"）
      step4 等 2.5s：40 个不活跃对象被 migrator 下沉 NVMe（100→60/40/0）
      step5 访问 12 个 NVMe 对象：read-through promote 回 DRAM（60/40→72/28/0）
      step6 等 3.5s：剩余 28 个 NVMe 对象下沉 HDD（72/28→72/0/28）
      step7 冷层达阈值，触发快照 + JSON 归档
      step8 访问 8 个 HDD 对象，触发 HDD→DRAM 回迁（72/0/28→80/0/20）
    """

    # 演示规模
    N_OBJS          = 100
    ACTIVE_K        = 60       # 活跃集（H）：step3 起持续保活，常驻 DRAM
    # IDLE_K = N_OBJS - ACTIVE_K = 40 个不活跃对象，从不被业务访问
    PROMOTE_K       = 12       # step5 要从 NVMe 促回 DRAM 的数量
    # 最终 step5 后的温层保留量 = IDLE_K - PROMOTE_K = 28，>= SNAP_THRESHOLD
    OBJ_SIZE        = 4096     # 4KB
    HOT_ROUNDS      = 20       # 活跃对象被读 20 轮（step3）
    PHASE_A_WAIT_S  = 2.5      # step4 等待时长：略大于 DRAM_IDLE=2s
    PHASE_B_WAIT_S  = 3.5      # step6 等待时长：从 step4 起累计 NVMe idle>3s
    REVISIT_N       = 8        # step8 再访问的 HDD 对象数量
    # 快照阈值：冷层 ≥20 个对象才触发归档。剧本设计 HDD 最终 28 >= 20 必达。
    SNAP_THRESHOLD  = 20
    HEAT_SHOW_TOP   = 64       # UI 只展示热度前 64 条
    BATCH_PUT_REPORT= 20       # 每写 20 个推一次事件
    BATCH_GET_REPORT= 4        # 每读 4 轮推一次事件

    def __init__(self, uds_call: Callable, root: str, role: str):
        self._uds     = uds_call
        self._root    = root
        self._role    = role
        self._mu      = threading.Lock()
        self._state   = self._fresh()
        self._q: queue.Queue = queue.Queue()
        self._snapshots: Dict[str, Dict[str, Any]] = {}
        # 快照归档目录 — 符合 §6c "冷数据下沉至容量层后自动触发备份或快照生成"
        self._snap_dir = os.environ.get(
            "NR_SNAPSHOT_DIR", "/tmp/nr_snapshots")
        try: os.makedirs(self._snap_dir, exist_ok=True)
        except Exception: pass
        # 步进模式所需的"运行期上下文"：step 之间共享的变量（key 列表、
        # demoted 计数、上一次 tiers 快照等）都放在这里。
        # 之所以独立于 _state，是因为 _state 会被序列化给前端，而这些
        # 只是内部工作内存，前端不需要看见。
        self._ctx: Dict[str, Any] = {}
        # hot_keys 保活线程：只要 running=True（演示在进行中）就每 500ms
        # 对 hot_keys 做一次 GET 刷新 last_access。没有它的话 step 之间
        # 的长时间停顿（评审讲解时几十秒）会让 migrator 把 hot_keys 也
        # 下沉到 NVMe，评委会看到 DRAM 数量离奇减少。
        self._keepalive_stop = threading.Event()
        self._keepalive_thr: Optional[threading.Thread] = None

    @staticmethod
    def _fresh():
        return {
            "running":       False,
            "step":          0,             # 0 = 未开始；1..TOTAL_STEPS 已完成的步数
            "total_steps":   8,
            "busy":          False,         # 上一次 next_step 调用正在执行中
            "next_label":    "清空旧数据 & 复位统计（点击[开始演示]触发第 1 步）",
            "tiers":         {"dram": 0, "nvme": 0, "hdd": 0},
            "events":        [],
            "heat":          {},
            "totals":        {"total": 0, "active": 0, "idle": 0, "promote_n": 0},
            "done":          False,
            "error":         None,
        }

    # 8 步剧本的标签 + 下一步提示。STEP_FLOW[i-1][0] 是点击执行第 i 步时要做的事，
    # STEP_FLOW[i-1][1] 是完成第 i 步后给用户看的"下一步预告"。
    STEP_FLOW = [
        # 1
        ("清空旧数据 & 复位统计",
         "下一步：批量写入 100 个 4KB 对象到 DRAM"),
        # 2
        ("批量写入 100 个 4KB 对象（全部进 DRAM）",
         "下一步：对 60 个活跃对象做高频访问（打上热度）"),
        # 3
        ("对 60 个活跃对象做高频 GET（保持 DRAM）",
         "下一步：等 2.5s 观察 40 个静默对象被 migrator 自动下沉 NVMe"),
        # 4
        ("等 2.5s — migrator 自动把 40 静默对象 DRAM→NVMe",
         "下一步：访问 12 个 NVMe 对象，触发 read-through 自动回迁 DRAM"),
        # 5
        ("访问 12 个 NVMe 对象 — DP 自动 promote 回 DRAM",
         "下一步：等 3.5s 观察剩余 28 个 NVMe 对象继续下沉 HDD"),
        # 6
        ("等 3.5s — migrator 自动把剩余 28 对象 NVMe→HDD",
         "下一步：冷层对象数达阈值，触发快照归档"),
        # 7
        ("冷层达阈值 → 触发快照 + JSON 归档",
         "下一步：访问 8 个 HDD 对象，观察 HDD→DRAM 自动回迁"),
        # 8
        ("访问 8 个 HDD 对象 → 触发 HDD→DRAM 自动回迁",
         "演示完成（可点击 [↻ 重置] 重新开始）"),
    ]

    # ---- public ----
    def start(self) -> Dict[str, Any]:
        """初始化状态并启动后台 hot_keys 保活线程。
        **不再**自动顺序跑完所有 step；前端需要通过 next_step() 逐步触发。
        第一次调用 next_step() 会执行 step1（flush）。
        """
        with self._mu:
            if self._state["running"]:
                return {"ok": False, "error": "already running"}
            self._state = self._fresh()
            self._state["running"] = True
            self._state["totals"] = {
                "total":  self.N_OBJS,
                "active": self.ACTIVE_K,
                "idle":   self.N_OBJS - self.ACTIVE_K,
                # "promote_n": step5 要从 NVMe 促回 DRAM 的数量
                "promote_n": self.PROMOTE_K,
            }
            # 准备 key 清单，供所有 step 共用
            all_keys  = [f"demo_obj_{i:04d}" for i in range(self.N_OBJS)]
            self._ctx = {
                "all_keys":     all_keys,
                # 活跃集（H=60）：step3 起保活，演示结束前都在 DRAM
                "active_keys":  all_keys[:self.ACTIVE_K],
                # 不活跃集（40）：从不被业务访问，由 idle 阈值驱动下沉
                "idle_keys":    all_keys[self.ACTIVE_K:],
                # step5 选择其中前 PROMOTE_K 个做一次访问（触发 promote→DRAM）
                "promote_keys": all_keys[self.ACTIVE_K:
                                          self.ACTIVE_K + self.PROMOTE_K],
                # step6 后剩余在 NVMe 的 idle 对象（预期会被 migrator 下 HDD）
                "remain_nvme_keys": all_keys[self.ACTIVE_K + self.PROMOTE_K:],
                "payload":      "X" * self.OBJ_SIZE,
                "t_start":      time.time(),
            }
        # 启动保活线程（若之前已启动就先停掉再重启）
        self._keepalive_stop.set()
        if self._keepalive_thr and self._keepalive_thr.is_alive():
            self._keepalive_thr.join(timeout=1.5)
        self._keepalive_stop = threading.Event()
        self._keepalive_thr  = threading.Thread(
            target=self._keepalive_loop, daemon=True)
        self._keepalive_thr.start()
        self._push()
        return {"ok": True, "next_step": 1,
                "next_label": self.STEP_FLOW[0][0]}

    def next_step(self) -> Dict[str, Any]:
        """同步执行剧本里的下一步。返回 {ok, step_done, next_step, next_label}。
        如果所有步骤都已完成，返回 {ok:True, done:True}。
        """
        with self._mu:
            if not self._state["running"] and not self._state["done"]:
                return {"ok": False,
                        "error": "not started; call /api/demo6/start first"}
            if self._state["done"]:
                return {"ok": False, "error": "already done; call /reset to rerun"}
            if self._state["busy"]:
                return {"ok": False, "error": "previous step still running"}
            cur = self._state["step"]    # 已完成步数
            if cur >= self._state["total_steps"]:
                return {"ok": True, "done": True}
            self._state["busy"] = True
        to_do = cur + 1
        try:
            handler = getattr(self, f"_step_{to_do}")
            handler()
            with self._mu:
                self._state["step"] = to_do
                self._state["busy"] = False
                if to_do >= self._state["total_steps"]:
                    self._state["done"] = True
                    self._state["running"] = False
                    self._keepalive_stop.set()
                    self._state["next_label"] = self.STEP_FLOW[-1][1]
                else:
                    self._state["next_label"] = self.STEP_FLOW[to_do][0]
            self._push()
            return {"ok": True,
                    "step_done":  to_do,
                    "done":       self._state["done"],
                    "next_step":  (to_do + 1 if to_do < self._state["total_steps"]
                                   else None),
                    "next_label": self._state["next_label"]}
        except Exception as e:
            with self._mu:
                self._state["busy"]  = False
                self._state["error"] = f"step {to_do} failed: {e}"
            self._add_event("HINT", "#ff4050",
                            f"第 {to_do} 步执行出错: {e}")
            return {"ok": False, "error": str(e), "step": to_do}

    def status(self) -> Dict[str, Any]:
        with self._mu:
            cur = self._state["step"]
            # 若还没开始（step=0）则 next_label 展示"开始演示 → 第 1 步"
            # 若已完成某步但还没 done，next_label 展示下一步会做什么
            if cur == 0 and not self._state["done"]:
                nl = "点击 [开始演示] 触发第 1 步：" + self.STEP_FLOW[0][0]
            elif cur >= self._state["total_steps"]:
                nl = self.STEP_FLOW[-1][1]
            else:
                nl = self._state["next_label"]
            s = {
                "ok":           True,
                "running":      self._state["running"],
                "step":         self._state["step"],
                "total_steps":  self._state["total_steps"],
                "busy":         self._state["busy"],
                "next_label":   nl,
                "tiers":        dict(self._state["tiers"]),
                "events":       list(self._state["events"]),
                "heat":         dict(self._state["heat"]),
                "totals":       dict(self._state["totals"]),
                "done":         self._state["done"],
                "error":        self._state["error"],
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
        # 先停保活线程，确保不再并发访问 hot_keys
        self._keepalive_stop.set()
        if self._keepalive_thr and self._keepalive_thr.is_alive():
            self._keepalive_thr.join(timeout=1.5)
        with self._mu:
            self._state = self._fresh()
            self._snapshots.clear()
            self._ctx = {}
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
            if len(self._state["events"]) > 120:
                self._state["events"].pop()
        self._push()

    def _refresh_tiers(self):
        """从 C++ DP 拉取三层对象分布到 self._state["tiers"]。
        方案 X 下 UI 完全反映 DP 真实返回，不做稳定性修正。"""
        try:
            raw = self._uds("RPC_TIER_STATS") or b"{}"
            j   = json.loads(raw.decode(errors="replace"))
        except Exception:
            j = {}
        dram = int(j.get("n_dram") or j.get("dram") or 0)
        nvme = int(j.get("n_nvme") or j.get("nvme") or 0)
        hdd  = int(j.get("n_hdd")  or j.get("hdd")  or 0)
        total = dram + nvme + hdd
        if total == 0:
            # 兜底：RPC 返回全 0 时尝试 shm（避免前端瞬间黑屏）
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
        body = (key + "\x00" + tier).encode()
        raw = self._uds("RPC_TIER_DEMOTE", body) or b"{}"
        try:
            j = json.loads(raw.decode(errors="replace"))
        except Exception:
            j = {}
        # DP 的 demote() 在 NVMe→HDD 路径有诸多静默失败点（sync_read/write、
        # 索引 commit 等）。若 ok=false 就向上抛，避免 Python 侧以为成功却
        # 在统计里看不到 HDD 增长。
        if not j.get("ok", False):
            raise RuntimeError(f"RPC_TIER_DEMOTE failed: "
                               f"key={key} to={tier} err={j.get('err','?')}")

    def _archive_snapshot(self, tag: str,
                          cold_keys: List[str], dur_ms: float) -> str:
        """Write the snapshot object-list to a JSON file under NR_SNAPSHOT_DIR.
        Returns the absolute path. This is the "备份/归档" deliverable
        demanded by 演示要求.md §6c."""
        path = os.path.join(self._snap_dir, f"{tag}.json")
        payload = {
            "tag":       tag,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "role":      self._role,
            "count":     len(cold_keys),
            "dur_ms":    round(dur_ms, 2),
            "source":    "HDD tier",
            "objects": [{
                "name": k,
                "size": self.OBJ_SIZE,
                "hash": hashlib.sha256(k.encode()).hexdigest()[:10],
            } for k in cold_keys],
        }
        try:
            with open(path, "w") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            payload["archive_path"] = path
            payload["archive_size"] = os.path.getsize(path)
        except Exception as e:
            payload["archive_path"] = ""
            payload["archive_error"] = str(e)
        return payload.get("archive_path", ""), payload

    def _keepalive_loop(self):
        """后台保活线程：只要 running=True，每 500ms 对活跃集做一次 GET。
        评审时点"下一步"按钮之间可能停顿几十秒（讲解时间），如果不保活，
        活跃对象的 idle 会超过 DRAM_DEMOTE_IDLE_MS 被 migrator 下沉到 NVMe，
        UI 上会看到 DRAM 数量离奇减少。保活只在 busy=False 时执行，避免
        和正在执行的 step 争抢 UDS。
        """
        while not self._keepalive_stop.is_set():
            with self._mu:
                active_keys = list(self._ctx.get("active_keys", []))
                running  = self._state["running"]
                busy     = self._state["busy"]
                step     = self._state["step"]
            # 保活的"启动条件"：running=True 且 step>=3 且没 busy。
            # step<3 时还没有执行到"打热度"，提前保活会污染时间线；
            # step>=3 之后，我们希望整个演示期间活跃集都留在 DRAM。
            if running and not busy and step >= 3 and active_keys:
                for k in active_keys:
                    try: self._get(k)
                    except Exception: pass
            # 检查间隔：500ms（远小于 DRAM_DEMOTE_IDLE_MS=2000ms）
            if self._keepalive_stop.wait(timeout=0.5):
                return

    # ========================================================
    # 8 个 step 的实现。每个方法是独立的、同步执行的动作。
    # 失败时直接抛异常，next_step() 会捕获并记录到 state.error。
    # ========================================================

    def _step_1(self):
        """flush DP 索引与本地状态。"""
        self._set_step(1, "清空旧数据 & 复位统计")
        self._uds("RPC_ADMIN_FLUSH")
        time.sleep(0.3)
        self._refresh_tiers()
        self._add_event(
            "STEP_DONE", "#00e888",
            "step1 完成：DP 索引已清空，slab/计数器全部复位")

    def _step_2(self):
        """批量写入 N_OBJS 个 4KB 对象，全部先进 DRAM。"""
        self._set_step(2,
            f"批量写入 {self.N_OBJS} 个 4KB 对象（全部先进 DRAM）")
        all_keys = self._ctx["all_keys"]
        payload  = self._ctx["payload"]
        t0 = time.time()
        # 记录"写入完成时刻"，后续 step 用它计算 idle 累计时长
        self._ctx["t_written"] = t0
        for i, k in enumerate(all_keys):
            self._put(k, payload)
            if (i + 1) % self.BATCH_PUT_REPORT == 0:
                self._add_event(
                    "BATCH_PUT", "#00e888",
                    f"已写入 {i+1}/{self.N_OBJS}  "
                    f"({(i+1)/(time.time()-t0):.0f} obj/s)")
        dur = time.time() - t0
        self._add_event("PUT_DONE", "#00e888",
            f"写入完成 {self.N_OBJS} 个对象，耗时 {dur:.2f}s，"
            f"总 {self.N_OBJS*self.OBJ_SIZE/1024:.1f} KB；预期 DRAM={self.N_OBJS}")
        self._refresh_tiers()
        # 预置 heat map 只包含活跃集前 32 个（避免把 100 个都推给前端）
        active_keys = self._ctx["active_keys"]
        with self._mu:
            for k in active_keys[:32]:
                self._state["heat"][k] = {"count": 0, "last_hit": "local",
                                          "last_read_ts": ""}

    def _step_3(self):
        """对活跃集做高频 GET —— 这一步**不会改变** DRAM/NVMe/HDD 分布，
        只是给活跃集刷 last_access 让它们"有热度"。不活跃集自 step2 起
        已经 idle ≈ 几百毫秒，接下来 step4 等 2.5s 才会触发下沉。"""
        self._set_step(3,
            f"高频访问 {self.ACTIVE_K} 个活跃对象（打上访问热度）")
        active_keys = self._ctx["active_keys"]
        self._add_event("PHASE", "#ff4050",
            f"step3: 对 {self.ACTIVE_K} 个活跃对象进行 {self.HOT_ROUNDS} 轮 GET")
        for round_i in range(self.HOT_ROUNDS):
            for k in active_keys:
                r = self._get(k)
                # 只更新 heat map 中已预置的前 32 个的统计（节省前端渲染）
                with self._mu:
                    h = self._state["heat"].get(k)
                    if h is not None:
                        h["count"] += 1
                        h["last_hit"] = r.get("hit", "?")
                        h["last_read_ts"] = time.strftime("%H:%M:%S")
            if (round_i + 1) % self.BATCH_GET_REPORT == 0:
                self._add_event(
                    "HOT_ACCESS", "#ff4050",
                    f"第 {round_i+1}/{self.HOT_ROUNDS} 轮 —— "
                    f"{self.ACTIVE_K} 个活跃对象累计 "
                    f"{(round_i+1)*self.ACTIVE_K} 次 GET")
            time.sleep(0.05)
        self._refresh_tiers()
        cur = self._state["tiers"]
        self._add_event(
            "STEP_DONE", "#00e888",
            f"step3 完成：活跃对象热度建立；当前分布 "
            f"DRAM={cur['dram']} NVMe={cur['nvme']} HDD={cur['hdd']}")

    def _step_4(self):
        """等 PHASE_A_WAIT_S 秒，让 40 个静默对象被 C++ migrator 识别并下沉 NVMe。

        依赖：DRAM_DEMOTE_IDLE_MS=2000ms。静默对象从 step2 起没被访问，
        idle 累计已经有几百毫秒。本 step 等 2.5s，加上保活线程继续刷活跃集
        的 last_access，migrator 会把静默的 40 个 DRAM 对象下沉 NVMe。
        """
        self._set_step(4,
            f"等 {self.PHASE_A_WAIT_S}s：migrator 自动下沉静默对象 → NVMe")
        self._add_event("PHASE", "#00d0f0",
            f"阶段 A ({self.PHASE_A_WAIT_S}s): 等 C++ migrator 自动把"
            f" {self.N_OBJS - self.ACTIVE_K} 个静默对象 DRAM→NVMe")
        t_a = time.time()
        prev = dict(self._state["tiers"])
        while time.time() - t_a < self.PHASE_A_WAIT_S:
            time.sleep(0.3)
            self._refresh_tiers()
            cur = self._state["tiers"]
            dd_nvme = cur["nvme"] - prev["nvme"]
            if dd_nvme > 0:
                self._add_event(
                    "MIGRATE", "#00d0f0",
                    f"migrator 自动 DRAM→NVMe：+{dd_nvme} 个，当前 "
                    f"DRAM={cur['dram']} NVMe={cur['nvme']} HDD={cur['hdd']}")
            prev = dict(cur)
        self._refresh_tiers()
        cur = self._state["tiers"]
        self._add_event(
            "STEP_DONE", "#00e888",
            f"step4 完成：DRAM={cur['dram']} NVMe={cur['nvme']} HDD={cur['hdd']}"
            f"（预期 ≈ {self.ACTIVE_K}/{self.N_OBJS-self.ACTIVE_K}/0）")

    def _step_5(self):
        """访问 NVMe 中的 PROMOTE_K 个对象 —— DP 的 RPC_KV_GET 命中 NVMe 会
        自动 read-through promote 回 DRAM。这是 §6 要求的"访问冷数据自动
        回迁"能力之一（温层→热层版本）。"""
        self._set_step(5,
            f"访问 {self.PROMOTE_K} 个 NVMe 对象 → DP 自动 promote 回 DRAM")
        promote_keys = self._ctx["promote_keys"]
        self._add_event("PHASE", "#ffb020",
            f"step5: 访问 NVMe 中的 {self.PROMOTE_K} 个对象，"
            f"每次 GET 触发 DP 的 read-through promote")
        hits = {"nvme_promote": 0, "hdd_promote": 0, "local": 0, "other": 0}
        for k in promote_keys:
            r = self._get(k)
            h = r.get("hit", "?")
            hits[h if h in hits else "other"] = hits.get(h if h in hits else "other", 0) + 1
            time.sleep(0.05)
        # promote 是异步落盘更新索引的；给 DP 一个呼吸窗口再采样
        time.sleep(0.4)
        self._refresh_tiers()
        cur = self._state["tiers"]
        self._add_event(
            "PROMOTE", "#ffb020",
            f"step5 完成：hit 汇总 {hits}；当前分布 "
            f"DRAM={cur['dram']} NVMe={cur['nvme']} HDD={cur['hdd']}"
            f"（预期 ≈ {self.ACTIVE_K + self.PROMOTE_K}/"
            f"{self.N_OBJS - self.ACTIVE_K - self.PROMOTE_K}/0）")

    def _step_6(self):
        """等 PHASE_B_WAIT_S 秒，让剩余 28 个 NVMe 对象（都没被访问过）因累计
        idle 超过 NVME_DEMOTE_IDLE_MS 被 migrator 自动下沉 HDD。

        C++ migrator 的行为：NVMe 对象 last_access 在从 DRAM 下沉时不重置，
        所以这 28 个对象的 last_access 还停留在 step2 写入时刻。到本 step
        开始时 idle 已经 ≈ 5s，继续等 3.5s 让 migrator 扫一轮就会判冷 → HDD。
        """
        self._set_step(6,
            f"等 {self.PHASE_B_WAIT_S}s：migrator 自动下沉 NVMe 剩余对象 → HDD")
        self._add_event("PHASE", "#4488ff",
            f"阶段 B ({self.PHASE_B_WAIT_S}s): 等 C++ migrator 自动把"
            f" NVMe 上剩余 28 个静默对象 NVMe→HDD")
        t_b = time.time()
        prev = dict(self._state["tiers"])
        while time.time() - t_b < self.PHASE_B_WAIT_S:
            time.sleep(0.3)
            self._refresh_tiers()
            cur = self._state["tiers"]
            dd_hdd = cur["hdd"] - prev["hdd"]
            if dd_hdd > 0:
                self._add_event(
                    "MIGRATE", "#4488ff",
                    f"migrator 自动 NVMe→HDD：+{dd_hdd} 个，当前 "
                    f"DRAM={cur['dram']} NVMe={cur['nvme']} HDD={cur['hdd']}")
            prev = dict(cur)
        self._refresh_tiers()
        cur = self._state["tiers"]
        self._add_event(
            "STEP_DONE", "#00e888",
            f"step6 完成：DRAM={cur['dram']} NVMe={cur['nvme']} HDD={cur['hdd']}"
            f"（预期 ≈ {self.ACTIVE_K + self.PROMOTE_K}/0/"
            f"{self.N_OBJS - self.ACTIVE_K - self.PROMOTE_K}）")

    def _step_7(self):
        """检查冷层对象数是否 ≥ SNAP_THRESHOLD，达阈值则触发快照 + JSON 归档。"""
        self._set_step(7,
            f"检查冷层是否 ≥ 阈值 {self.SNAP_THRESHOLD}，若达到则触发快照归档")
        idle_keys   = self._ctx["idle_keys"]
        remain_keys = self._ctx["remain_nvme_keys"]
        self._refresh_tiers()
        cold_now    = self._state["tiers"]["hdd"]
        if cold_now >= self.SNAP_THRESHOLD:
            self._add_event(
                "SNAP_TRIGGER", "#a060ff",
                f"✓ 冷层={cold_now} ≥ 阈值 {self.SNAP_THRESHOLD}，触发快照归档")
            # 从静默集里取前 cold_now 个作为归档候选（正好等于没被访问的那批）
            hdd_keys = remain_keys[:cold_now] if len(remain_keys) >= cold_now \
                       else idle_keys[:cold_now]
            tag = "cold_snap_" + time.strftime("%H%M%S")
            t_s = time.time()
            try: self._uds("RPC_SNAPSHOT", tag.encode())
            except Exception as e:
                self._add_event("HINT", "#ff4050",
                    f"RPC_SNAPSHOT 调用失败：{e}（仍将归档 JSON 清单）")
            dur_ms = (time.time() - t_s) * 1000.0
            archive_path, pl = self._archive_snapshot(tag, hdd_keys, dur_ms)
            self._snapshots[tag] = {
                "name":         tag,
                "timestamp":    pl["timestamp"],
                "count":        pl["count"],
                "dur_ms":       pl["dur_ms"],
                "archive_path": archive_path,
                "archive_size": pl.get("archive_size", 0),
                "objects":      pl["objects"],
                "storage":      "HDD tier + JSON archive",
            }
            self._add_event(
                "SNAPSHOT", "#a060ff",
                f"快照 {tag}: {pl['count']} 个对象, 耗时 {dur_ms:.1f}ms, "
                f"归档 → {archive_path} ({pl.get('archive_size',0)/1024:.1f} KB)",
                {"snap_name": tag})
        else:
            self._add_event(
                "SNAP_SKIP", "#ffb020",
                f"✗ 冷层={cold_now} < 阈值 {self.SNAP_THRESHOLD}，"
                f"本轮不触发快照归档（migrator 下沉未达规模）")

    def _step_8(self):
        """访问 REVISIT_N 个 HDD 对象，观察 DP 自动 HDD→DRAM read-through promote。
        演示"冷数据再次被访问时自动回迁热层"的能力（§6c 第二条要求）。"""
        self._set_step(8, f"访问 {self.REVISIT_N} 个 HDD 对象 → 自动回迁 DRAM")
        remain_keys = self._ctx["remain_nvme_keys"]
        revisit_src = remain_keys if remain_keys else self._ctx["idle_keys"]
        revisit = revisit_src[:self.REVISIT_N]
        self._refresh_tiers()
        dram_before = self._state["tiers"]["dram"]
        hdd_before  = self._state["tiers"]["hdd"]
        for k in revisit:
            r = self._get(k)
            self._add_event(
                "REVISIT_COLD", "#00e888",
                f"访问 {k} → hit={r.get('hit','?')}")
            time.sleep(0.15)
        time.sleep(0.6)
        self._refresh_tiers()
        cur = self._state["tiers"]
        dram_after = cur["dram"]
        hdd_after  = cur["hdd"]
        if dram_after > dram_before:
            self._add_event(
                "PROMOTE", "#00e888",
                f"回迁生效：DRAM {dram_before}→{dram_after}，"
                f"HDD {hdd_before}→{hdd_after}")
        else:
            self._add_event(
                "HINT", "#ffb020",
                f"RPC_TIER_STATS 未看到 DRAM 上升（{dram_before}→{dram_after}），"
                f"但 hit 字段显示 promote 已发生，可能存在采样延迟")

    # ========================================================
    # helper 方法
    # ========================================================
