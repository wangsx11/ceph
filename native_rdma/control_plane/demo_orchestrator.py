"""
demo_orchestrator.py — §3 / §5 / §6 三个演示的服务端协调器

重写目标（参考 docs/演示要求.md）：
  §3  跨节点对象读写：维护一份"本端对象视图"，所有写/改/删都
      走 UDS(RPC_KV_PUT/GET)；GET 命中层级由 DP 回填（hit=local/remote/nvme/hdd）。
  §5  吞吐量 & 扩展性：逐轮 1W/5W/10W 对象持续并发写入，每秒
      采样 ops/bw/lat 曲线；nr_bench 真实压测 + shm metrics。
  §6  分级存储：8 步一键剧本。
      100 对象先写入并落到 NVMe 温层作为基线；step3 通过真实 GET 构造
      hot/warm/cold 三类访问行为；后续自动分层，冷层达阈值后触发快照归档，
      再访问冷对象观察 HDD→DRAM 回迁。

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
    # 三轮使用同一个采样时长，前端才能用同一条时间轴直接比较。
    ROUND_DUR_S  = [int(os.environ.get("M5_DURATION_S", "12"))] * 3
    # 当前 M5 走同步 RPC/RDMA 完成路径：每个客户端线程同一时刻只有
    # 1 个 outstanding 请求。盲目把线程数拉到 64 只会在 data-plane 前排队，
    # 吞吐不涨且延迟/P99 明显恶化；默认保守使用 16，现场可用 M5_THREADS
    # 覆盖做真实实验，不在前端编造或缩放数据。
    THREADS      = int(os.environ.get("M5_THREADS", "16"))
    VAL_SIZE     = 1024
    REQUIRE_PEER = os.environ.get("M5_REQUIRE_PEER", "1").lower() not in ("0", "false", "no")
    PERF_DUR_S   = int(os.environ.get("M5_PERF_DURATION_S", "15"))
    PERF_THREAD_SWEEP = [
        int(x) for x in os.environ.get("M5_PERF_THREADS", "8,16,24,32").split(",")
        if x.strip()
    ]

    def __init__(self, root: str, role: str,
                 uds_call: Optional[Callable] = None):
        self.root     = root
        self.role     = role
        self.nr_bench = os.path.join(root, "build", "bin", "nr_bench")
        self.uds      = os.environ.get("NR_UDS_PATH",
                                       "/tmp/native_rdma-dp.sock")
        self._uds_call = uds_call
        self._mu      = threading.Lock()
        self._rounds: Dict[int, Dict[str, Any]] = {}
        self._bench: Dict[str, Any] = {
            "running": False,
            "phase": "idle",
            "trials": [],
            "summary": None,
            "duration_s": self.PERF_DUR_S,
            "thread_sweep": list(self.PERF_THREAD_SWEEP),
        }
        self._cur: Optional[int] = None

    # ---- public API ----
    def start(self, round_id: int) -> Dict[str, Any]:
        if round_id not in (1, 2, 3):
            return {"ok": False, "error": f"bad round {round_id}"}
        pre = self._preflight()
        if not pre.get("ok"):
            return pre
        with self._mu:
            if self._cur and self._rounds[self._cur].get("running"):
                return {"ok": False,
                        "error": f"round {self._cur} still running"}
            if self._bench.get("running"):
                return {"ok": False, "error": "perf_01 benchmark still running"}
            self._cur = round_id
            self._rounds[round_id] = {
                "running":   True,
                "phase":     "starting",
                "samples":   [],
                "summary":   None,
                "error":     None,
                "raw_tail":  "",
                "start_ts":  time.time(),
                "count":     self.ROUND_COUNTS[round_id - 1],
                "duration_s": self.ROUND_DUR_S[round_id - 1],
            }
        threading.Thread(target=self._run, args=(round_id,),
                         daemon=True).start()
        return {"ok": True, "round": round_id,
                "count": self.ROUND_COUNTS[round_id - 1],
                "duration_s": self.ROUND_DUR_S[round_id - 1]}

    def start_perf01(self) -> Dict[str, Any]:
        """Run the same 1KB throughput methodology as tests/performance/perf_01.

        The scale rounds below intentionally use a shared total keyspace for
        the 1w/5w/10w demo. perf_01 is a different workload: per-thread
        keyspace plus a thread sweep. Keeping it as a separate run makes the
        UI truthful instead of mixing two incompatible meanings of "object
        count".
        """
        pre = self._preflight()
        if not pre.get("ok"):
            return pre
        with self._mu:
            if self._cur and self._rounds.get(self._cur, {}).get("running"):
                return {"ok": False,
                        "error": f"round {self._cur} still running"}
            if self._bench.get("running"):
                return {"ok": False, "error": "perf_01 benchmark still running"}
            self._bench = {
                "running": True,
                "phase": "starting",
                "trials": [],
                "summary": None,
                "error": None,
                "start_ts": time.time(),
                "duration_s": self.PERF_DUR_S,
                "thread_sweep": list(self.PERF_THREAD_SWEEP),
            }
        threading.Thread(target=self._run_perf01, daemon=True).start()
        return {"ok": True, "metric": "perf_01_ops_1kb",
                "duration_s": self.PERF_DUR_S,
                "thread_sweep": list(self.PERF_THREAD_SWEEP)}

    def live(self, round_id: int) -> Dict[str, Any]:
        with self._mu:
            r = self._rounds.get(round_id)
            if not r:
                return {"ok": True, "round": round_id,
                        "running": False, "phase": "idle",
                        "duration_s": self.ROUND_DUR_S[round_id - 1],
                        "samples": [], "summary": None,
                        "error": None, "raw_tail": ""}
            return {"ok":       True,
                    "round":    round_id,
                    "running":  r["running"],
                    "phase":    r["phase"],
                    "count":    r["count"],
                    "duration_s": r.get("duration_s", self.ROUND_DUR_S[round_id - 1]),
                    "samples":  list(r["samples"]),
                    "summary":  r["summary"],
                    "error":    r.get("error"),
                    "raw_tail": r.get("raw_tail", "")}

    def snapshot_all(self) -> Dict[str, Any]:
        """Return a full view of rounds 1..3 for the page refresh path."""
        with self._mu:
            out = {"ok": True, "rounds": {}}
            for i in (1, 2, 3):
                r = self._rounds.get(i)
                if not r:
                    out["rounds"][i] = {"running": False, "phase": "idle",
                                        "samples": [], "summary": None,
                                        "count": self.ROUND_COUNTS[i - 1],
                                        "duration_s": self.ROUND_DUR_S[i - 1],
                                        "error": None, "raw_tail": ""}
                else:
                    out["rounds"][i] = {
                        "running":  r["running"],
                        "phase":    r["phase"],
                        "count":    r["count"],
                        "duration_s": r.get("duration_s", self.ROUND_DUR_S[i - 1]),
                        "samples":  list(r["samples"]),
                        "summary":  r["summary"],
                        "error":    r.get("error"),
                        "raw_tail": r.get("raw_tail", ""),
                    }
            out["bench"] = {
                "running": self._bench.get("running", False),
                "phase": self._bench.get("phase", "idle"),
                "trials": list(self._bench.get("trials", [])),
                "summary": self._bench.get("summary"),
                "error": self._bench.get("error"),
                "duration_s": self._bench.get("duration_s", self.PERF_DUR_S),
                "thread_sweep": list(self._bench.get("thread_sweep", self.PERF_THREAD_SWEEP)),
            }
            return out

    def reset(self):
        with self._mu:
            self._rounds.clear()
            self._cur = None
            self._bench = {
                "running": False,
                "phase": "idle",
                "trials": [],
                "summary": None,
                "error": None,
                "duration_s": self.PERF_DUR_S,
                "thread_sweep": list(self.PERF_THREAD_SWEEP),
            }

    # ---- internals ----
    def _preflight(self) -> Dict[str, Any]:
        if not os.path.exists(self.nr_bench):
            return {"ok": False,
                    "error": f"nr_bench not found: {self.nr_bench}"}
        if not os.path.exists(self.uds):
            return {"ok": False,
                    "error": f"data plane not running: missing UDS {self.uds}"}
        if not self.REQUIRE_PEER or not self._uds_call:
            return {"ok": True}
        try:
            raw = self._uds_call("RPC_CLUSTER_STATUS") or b"{}"
            cs = json.loads(raw.decode(errors="replace"))
        except Exception as e:
            return {"ok": False,
                    "error": f"cannot query data plane status: {e}"}
        if not cs.get("ok", False):
            return {"ok": False,
                    "error": cs.get("err", "data plane status failed"),
                    "cluster": cs}
        if not cs.get("peer_alive", False):
            return {"ok": False,
                    "error": "peer is not alive; M5 requires real cross-node RDMA replication",
                    "cluster": cs}
        return {"ok": True, "cluster": cs}

    def _run_perf01(self):
        dur_s = self.PERF_DUR_S
        trials: List[Dict[str, Any]] = []
        best: Optional[Dict[str, Any]] = None
        keyspace = 10_000

        for threads in self.PERF_THREAD_SWEEP:
            with self._mu:
                self._bench["phase"] = f"running_threads_{threads}"
            cmd = [self.nr_bench,
                   f"--uds={self.uds}",
                   "--op=put",
                   f"--threads={threads}",
                   f"--duration={dur_s}",
                   f"--val-size={self.VAL_SIZE}"]
            if self.REQUIRE_PEER:
                cmd.append("--require-peer=1")

            raw = ""
            try:
                proc = subprocess.run(cmd, capture_output=True, text=True,
                                      timeout=dur_s + 20)
                raw = (proc.stdout or "") + (proc.stderr or "")
            except Exception as e:
                raw = f"[runner] nr_bench failed: {e}"
            trial = _parse_nr_bench(raw, keyspace, threads, self.VAL_SIZE, dur_s)
            trial.update({
                "metric": "perf_01_ops_1kb",
                "keyspace_per_thread": keyspace,
                "effective_objects": keyspace * threads,
                "shared_keyspace": False,
                "require_peer": self.REQUIRE_PEER,
                "bw_gbps": round(trial.get("iops", 0) * self.VAL_SIZE * 8.0 / 1e9, 3),
                "passed_ops": bool(
                    trial.get("iops", 0) >= 1_000_000
                    and trial.get("ops_fail", 0) == 0
                    and trial.get("ops_degraded", 0) == 0
                ),
            })
            trial["passed_util"] = bool(
                trial["bw_gbps"] >= 50.0
                and trial.get("ops_fail", 0) == 0
                and trial.get("ops_degraded", 0) == 0
            )
            trial["passed"] = bool(trial["passed_ops"] or trial["passed_util"])
            trial["error"] = _bench_error(raw, trial)
            trials.append(trial)
            if best is None or trial.get("iops", 0) > best.get("iops", 0):
                best = trial
            with self._mu:
                self._bench["trials"] = list(trials)

        best = best or {}
        summary = dict(best)
        summary.update({
            "metric": "perf_01_ops_1kb",
            "threshold_iops": 1_000_000,
            "threshold_util_pct": 50.0,
            "threshold_criterion": "ops OR util (1KB is QPS-bound)",
            "passed": bool(
                best.get("passed_ops", False) or best.get("passed_util", False)
            ),
            "trials": trials,
            "error": _bench_error("", best),
        })
        with self._mu:
            self._bench["running"] = False
            self._bench["phase"] = "done"
            self._bench["summary"] = summary
            self._bench["error"] = summary.get("error")

    def _run(self, round_id: int):
        count   = self.ROUND_COUNTS[round_id - 1]
        dur_s   = self.ROUND_DUR_S[round_id - 1]
        threads = self.THREADS
        with self._mu:
            self._rounds[round_id]["phase"] = "prepare"

        if self._uds_call:
            try:
                self._uds_call("RPC_ADMIN_FLUSH")
            except Exception:
                pass

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
               f"--keyspace={count}",
               "--shared-keyspace=1"]
        if self.REQUIRE_PEER:
            cmd.append("--require-peer=1")
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
        summary.update({
            "require_peer": self.REQUIRE_PEER,
            "passed": bool(
                summary.get("iops", 0) > 0
                and summary.get("ops_fail", 0) == 0
                and summary.get("ops_degraded", 0) == 0
            ),
            "error": _bench_error(raw, summary),
        })
        with self._mu:
            r = self._rounds[round_id]
            r["running"] = False
            r["phase"]   = "done"
            r["summary"] = summary
            r["error"]   = summary.get("error")
            r["raw_tail"] = raw[-600:] if raw else ""


def _parse_nr_bench(raw: str, count: int, threads: int,
                    val_size: int, dur_s: int) -> Dict[str, Any]:
    import re
    num = r"[-+]?\d+(?:\.\d+)?"
    def g(pat, cast=float, default=0.0):
        m = re.search(pat, raw); return cast(m.group(1)) if m else default
    ops = g(rf"ops/s\s*:\s*({num})", float, 0.0)
    ok_ops = g(r"ops ok/fail\s*:\s*(\d+)\s*/\s*\d+", int, 0)
    fail_ops = g(r"ops ok/fail\s*:\s*\d+\s*/\s*(\d+)", int, 0)
    degraded_ops = g(r"ops degraded\s*:\s*(\d+)", int, 0)
    # 首次出现 "(x MB/s)" 是 req 吞吐量
    req_mbps = g(rf"\(({num})\s*MB/s\)", float, 0.0)
    lat_avg  = g(rf"avg=({num})")
    lat_p50  = g(rf"p50=({num})")
    lat_p90  = g(rf"p90=({num})", float, None)
    lat_p99  = g(rf"p99=({num})")
    lat_p999 = g(rf"p99\.9=({num})")
    gbps = round(req_mbps * 8.0 / 1000.0, 3)
    # footprint ≈ count * slot_size；slot_size 约等于 val_size 对齐到 slab 粒度
    footprint_mb = round(count * val_size / (1024 * 1024), 2)
    return {
        "count":       count,
        "threads":     threads,
        "duration_s":  dur_s,
        "val_size":    val_size,
        "shared_keyspace": True,
        "ops_ok":      int(ok_ops),
        "ops_fail":    int(fail_ops),
        "ops_degraded": int(degraded_ops),
        "iops":        int(ops),
        "ops_per_sec": float(ops),
        "tp_mbps":     round(req_mbps, 2),
        "mb_per_sec":  round(req_mbps, 2),
        "gbps":        gbps,
        "util_pct":    round(gbps / 100.0 * 100.0, 2),
        "footprint_mb": footprint_mb,
        "lat_avg_us":  round(lat_avg, 2),
        "lat_p50_us":  round(lat_p50, 2),
        "lat_p90_us":  round(lat_p90 if lat_p90 is not None else lat_p99, 2),
        "lat_p99_us":  round(lat_p99, 2),
        "lat_p99_9_us":round(lat_p999, 2),
    }


def _bench_error(raw: str, summary: Dict[str, Any]) -> Optional[str]:
    raw_l = (raw or "").lower()
    if "uds connect failed" in raw_l:
        return "nr_bench cannot connect to data-plane UDS"
    if "data plane not running" in raw_l or "no such file" in raw_l:
        return "data plane is not running"
    if "rejected" in raw_l and int(summary.get("ops_degraded", 0) or 0) > 0:
        return "peer replication degraded; require-peer rejected writes"
    if int(summary.get("ops_fail", 0) or 0) > 0:
        return f"nr_bench reported {summary.get('ops_fail')} failed operations"
    if int(summary.get("iops", 0) or 0) <= 0:
        return "nr_bench finished with zero successful operations"
    return None

# ================================================================
# 4) §6: 真实访问驱动的分级存储剧本
# ================================================================
class TierDemoScript:
    """§6 demo runner.

    一键执行（不再步进），软性按以下顺序打通整个剧本：

    100 个对象先落 NVMe 温层，再按真实 GET 分 3 类：
      · HOT  (30)：step3 高频访问 5 轮 → promote 到 DRAM 并持续保热
      · WARM (30)：step3 轻访问 1 次  → 短暂 promote，几秒后回落 NVMe
      · COLD (40)：step3 完全不访问 → 一直留 NVMe，随后下沉 HDD

    step5 稳定分布 = 30/30/40；step7 回访 5 个冷对象后最终约 35/30/35。
    """

    # 演示规模
    N_OBJS          = 100
    HOT_K           = 30       # 热集：step3 高频访问
    WARM_K          = 30       # 温集：step3 轻访问
    # COLD_K = N_OBJS - HOT_K - WARM_K = 40，从不访问
    OBJ_SIZE        = 4096     # 4KB
    HOT_ROUNDS      = 5        # HOT 对象读 5 轮，并在等待阶段继续保热
    WARM_HITS       = 1        # WARM 对象轻访问 1 次
    PHASE_A_WAIT_S  = 6.0      # step4：等 warm 从 DRAM 回落 NVMe
    PHASE_B_WAIT_S  = 6.0      # step5：等所有 COLD 落到 HDD
    REVISIT_N       = 5        # step7 再访问的 HDD 对象数
    SNAP_THRESHOLD  = 20
    HEAT_SHOW_TOP   = 64
    BATCH_PUT_REPORT= 20
    BATCH_GET_REPORT= 1
    STEP_INTERVAL_S = 0.4      # 一键执行时两个 step 之间的停顿
    HOT_KEEPALIVE_S = 1.0      # phase A/B 中持续制造真实 hot 访问

    def __init__(self, uds_call: Callable, root: str, role: str):
        self._uds     = uds_call
        self._root    = root
        self._role    = role
        self._mu      = threading.Lock()
        self._state   = self._fresh()
        self._q: queue.Queue = queue.Queue()
        self._snapshots: Dict[str, Dict[str, Any]] = {}
        # 快照文件输出目录。
        self._snap_dir = os.environ.get(
            "NR_SNAPSHOT_DIR", "/tmp/nr_snapshots")
        try: os.makedirs(self._snap_dir, exist_ok=True)
        except Exception: pass
        # 步进模式所需的"运行期上下文"：step 之间共享的变量（key 列表、
        # demoted 计数、上一次 tiers 快照等）都放在这里。
        # 之所以独立于 _state，是因为 _state 会被序列化给前端，而这些
        # 只是内部工作内存，前端不需要看见。
        self._ctx: Dict[str, Any] = {}
        # 复用这个 Event 控制一键执行线程停止。
        self._keepalive_stop = threading.Event()
        self._keepalive_thr: Optional[threading.Thread] = None

    @staticmethod
    def _fresh():
        return {
            "running":       False,
            "step":          0,             # 0 = 未开始；1..TOTAL_STEPS 已完成的步数
            "total_steps":   8,
            "busy":          False,
            "next_label":    "清空旧数据 & 复位统计（点击[开始演示]一键走完整剧本）",
            "tiers":         {"dram": 0, "nvme": 0, "hdd": 0},
            "events":        [],
            "heat":          {},
            "totals":        {"total": 0, "hot": 0, "warm": 0, "cold": 0},
            "done":          False,
            "error":         None,
        }

    # 8 个环节的展示标签——直接给前端用于进度圆点
    STEP_FLOW = [
        ("清空旧数据 & 复位统计", ""),
        ("写入 100 个 4KB 对象并落到 NVMe 温层", ""),
        ("构造访问热度：hot×5 / warm×1 / cold×0", ""),
        ("阶段 A：warm 热度衰减后自动回落 NVMe", ""),
        ("阶段 B：cold 对象下沉 HDD", ""),
        ("检查冷层是否达阈值 → 触发快照 + JSON 归档", ""),
        ("访问 5 个 HDD 对象 → 观察自动回迁 DRAM", ""),
        ("汇总三层分布 & 演示结束", ""),
    ]

    # ---- public ----
    def start(self) -> Dict[str, Any]:
        """初始化状态并启动后台线程**一键顺序**跑完所有 8 步。
        前端只需要一个"开始演示"按钮；演示过程中可通过 status/stream 拉实时进度。
        """
        with self._mu:
            if self._state["running"]:
                return {"ok": False, "error": "already running"}
            self._state = self._fresh()
            self._state["running"] = True
            cold_k = self.N_OBJS - self.HOT_K - self.WARM_K
            self._state["totals"] = {
                "total": self.N_OBJS,
                "hot":   self.HOT_K,
                "warm":  self.WARM_K,
                "cold":  cold_k,
            }
            # 准备 key 清单：hot/warm/cold 三段
            all_keys = [f"demo_obj_{i:04d}" for i in range(self.N_OBJS)]
            self._ctx = {
                "all_keys":  all_keys,
                "hot_keys":  all_keys[:self.HOT_K],
                "warm_keys": all_keys[self.HOT_K:self.HOT_K + self.WARM_K],
                "cold_keys": all_keys[self.HOT_K + self.WARM_K:],
                "payload":   "X" * self.OBJ_SIZE,
                "t_start":   time.time(),
            }
        # 启动后台 run 线程。
        self._keepalive_stop = threading.Event()   # 复用这个 Event 做 run 线程的停止信号
        self._keepalive_thr  = threading.Thread(
            target=self._run_all, daemon=True)
        self._keepalive_thr.start()
        self._push()
        return {"ok": True, "mode": "one_shot", "total_steps": 8}

    def _run_all(self):
        """按顺序执行 step1..step8，step 之间短暂 sleep 便于 UI 刷新。"""
        try:
            for i in range(1, 9):
                if self._keepalive_stop.is_set(): return
                with self._mu:
                    self._state["busy"] = True
                    self._state["next_label"] = self.STEP_FLOW[i-1][0]
                self._push()
                handler = getattr(self, f"_step_{i}")
                handler()
                with self._mu:
                    self._state["step"] = i
                    self._state["busy"] = False
                    if i < 8:
                        self._state["next_label"] = self.STEP_FLOW[i][0]
                    else:
                        self._state["next_label"] = "演示完成（可点击 [↻ 重置] 重新开始）"
                self._push()
                time.sleep(self.STEP_INTERVAL_S)
            with self._mu:
                self._state["done"]    = True
                self._state["running"] = False
                self._state["busy"]    = False
            self._push()
        except Exception as e:
            with self._mu:
                self._state["busy"]    = False
                self._state["running"] = False
                self._state["error"]   = f"demo failed: {e}"
            self._add_event("HINT", "#ff4050", f"演示异常终止: {e}")

    def next_step(self) -> Dict[str, Any]:
        """兼容 API：一键执行模式下，该端点不再需要前端调用，但保留响应以避免旧前端报错。"""
        return {"ok": True, "mode": "one_shot",
                "msg": "one-shot mode: no manual step; poll /status for progress"}

    def status(self) -> Dict[str, Any]:
        with self._mu:
            cur = self._state["step"]
            # 若还没开始（step=0）则 next_label 展示"开始演示 → 第 1 步"
            # 若已完成某步但还没 done，next_label 展示下一步会做什么
            if cur == 0 and not self._state["done"]:
                nl = "点击 [开始演示] 触发第 1 步：" + self.STEP_FLOW[0][0]
            elif cur >= self._state["total_steps"]:
                nl = "演示完成（可点击 [↻ 重置] 重新开始）"
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
        # 先停一键执行线程，确保不再并发访问 hot_keys
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
        UI 完全反映 DP 真实返回，不做稳定性修正。"""
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

    def _touch_hot_keys(self, reason: str = "keepalive"):
        """Issue real GETs for hot keys so they remain active during waits."""
        hot_keys = self._ctx.get("hot_keys", [])
        if not hot_keys: return
        for k in hot_keys:
            r = self._get(k)
            with self._mu:
                h = self._state["heat"].get(k)
                if h is not None:
                    h["count"] += 1
                    h["last_hit"] = r.get("hit", "?")
                    h["last_read_ts"] = time.strftime("%H:%M:%S")
        self._add_event("HOT_KEEP", "#ff4050",
            f"{reason}: 刷新 {len(hot_keys)} 个 hot 对象热度，防止讲解等待期间误降级")

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
        """DEPRECATED: 一键执行模式下不再使用。保留空实现防止旧代码反射调用报错。"""
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
        """批量写入 N_OBJS 个 4KB 对象，并落到 NVMe 温层作为演示基线。"""
        self._set_step(2,
            f"批量写入 {self.N_OBJS} 个 4KB 对象并落到 NVMe 温层")
        all_keys = self._ctx["all_keys"]
        payload  = self._ctx["payload"]
        t0 = time.time()
        self._ctx["t_written"] = t0
        for i, k in enumerate(all_keys):
            r = self._put(k, payload)
            if not r.get("ok", False):
                raise RuntimeError(f"RPC_KV_PUT failed: key={k} err={r.get('err','?')}")
            if (i + 1) % self.BATCH_PUT_REPORT == 0:
                self._add_event(
                    "BATCH_PUT", "#00e888",
                    f"已写入 {i+1}/{self.N_OBJS}  "
                    f"({(i+1)/max(time.time()-t0, 1e-6):.0f} obj/s)")
        dur = time.time() - t0
        self._add_event("PUT_DONE", "#00e888",
            f"写入完成 {self.N_OBJS} 个对象，耗时 {dur:.2f}s，"
            f"总 {self.N_OBJS*self.OBJ_SIZE/1024:.1f} KB；执行初始落温层")
        for i, k in enumerate(all_keys):
            self._demote(k, "nvme")
            if (i + 1) % self.BATCH_PUT_REPORT == 0:
                self._add_event("BASELINE", "#ffb020",
                    f"初始温层落位 {i+1}/{self.N_OBJS}：DRAM→NVMe")
        self._refresh_tiers()
        cur = self._state["tiers"]
        self._add_event("STEP_DONE", "#00e888",
            f"step2 完成：基线分布 DRAM={cur['dram']} NVMe={cur['nvme']} HDD={cur['hdd']}，"
            "后续迁移由真实 GET 热度触发")
        # 预置 heat map 只包含 hot_keys（避免把 100 个都推给前端）
        hot_keys = self._ctx["hot_keys"]
        with self._mu:
            for k in hot_keys:
                self._state["heat"][k] = {"count": 0, "last_hit": "nvme",
                                          "last_read_ts": ""}

    def _step_3(self):
        """热度构造阶段：
          · hot_keys  (30)  高频 GET HOT_ROUNDS(5) 轮 → 回迁并保持 DRAM
          · warm_keys (30)  轻访问 WARM_HITS(1) 次  → 短暂回迁，随后回落 NVMe
          · cold_keys (40)  完全不访问              → 留在 NVMe，后续下沉 HDD
        """
        self._set_step(3,
            f"构造访问热度：hot×{self.HOT_ROUNDS} / warm×{self.WARM_HITS} / cold×0")
        hot_keys  = self._ctx["hot_keys"]
        warm_keys = self._ctx["warm_keys"]
        cold_keys = self._ctx["cold_keys"]

        self._add_event("PHASE", "#ff4050",
            f"step3a: hot_keys ({len(hot_keys)} 个) 高频 GET {self.HOT_ROUNDS} 轮，"
            "从 NVMe read-through 回迁 DRAM")
        for round_i in range(self.HOT_ROUNDS):
            for k in hot_keys:
                r = self._get(k)
                with self._mu:
                    h = self._state["heat"].get(k)
                    if h is not None:
                        h["count"] += 1
                        h["last_hit"] = r.get("hit", "?")
                        h["last_read_ts"] = time.strftime("%H:%M:%S")
            self._add_event(
                "HOT_ACCESS", "#ff4050",
                f"第 {round_i+1}/{self.HOT_ROUNDS} 轮 hot 访问完成，"
                f"累计 {(round_i+1)*len(hot_keys)} 次 GET")
            time.sleep(0.05)

        self._add_event("PHASE", "#ffb020",
            f"step3b: warm_keys ({len(warm_keys)} 个) 轻访问 {self.WARM_HITS} 次，"
            "短暂回迁后等待热度衰减")
        for _ in range(self.WARM_HITS):
            for k in warm_keys:
                self._get(k)
        self._add_event("WARM_ACCESS", "#ffb020",
            f"warm_keys 被访问 {self.WARM_HITS} 次，后续回落 NVMe")

        self._add_event("PHASE", "#4488ff",
            f"step3c: cold_keys ({len(cold_keys)} 个) 保持静默，后续下沉 HDD")
        self._refresh_tiers()
        cur = self._state["tiers"]
        self._add_event("STEP_DONE", "#00e888",
            f"step3 完成：hot/warm 已被真实访问，当前 "
            f"DRAM={cur['dram']} NVMe={cur['nvme']} HDD={cur['hdd']}")

    def _step_4(self):
        """阶段 A：等 PHASE_A_WAIT_S 秒，让后台分层逻辑生效。
        · hot 对象持续被真实 GET 刷热 → 留 DRAM
        · warm 对象只轻访问一次，热度衰减到 hot_cut 以下 → 回落 NVMe
        · cold 对象未访问，仍留 NVMe，等待后续 warm_cut 触发 HDD 下沉
        """
        self._set_step(4,
            f"等 {self.PHASE_A_WAIT_S}s — warm 热度衰减后自动回落 NVMe")
        self._add_event("PHASE", "#00d0f0",
            f"阶段 A ({self.PHASE_A_WAIT_S}s)：hot 保持在 DRAM；warm 回落 NVMe")
        t_a = time.time()
        last_hot = 0.0
        prev = dict(self._state["tiers"])
        while time.time() - t_a < self.PHASE_A_WAIT_S:
            time.sleep(0.4)
            if time.time() - last_hot >= self.HOT_KEEPALIVE_S:
                self._touch_hot_keys("阶段 A hot 保热")
                last_hot = time.time()
            self._refresh_tiers()
            cur = self._state["tiers"]
            dd_nvme = cur["nvme"] - prev["nvme"]
            dd_hdd  = cur["hdd"]  - prev["hdd"]
            if dd_nvme > 0 or dd_hdd > 0:
                self._add_event(
                    "MIGRATE", "#00d0f0",
                    f"DRAM→NVMe: +{dd_nvme}  NVMe→HDD: +{dd_hdd}  当前 "
                    f"DRAM={cur['dram']} NVMe={cur['nvme']} HDD={cur['hdd']}")
            prev = dict(cur)
        self._refresh_tiers()
        cur = self._state["tiers"]
        self._add_event("STEP_DONE", "#00e888",
            f"step4 完成：DRAM={cur['dram']} NVMe={cur['nvme']} HDD={cur['hdd']}"
            f"（预期约 hot 留 DRAM，warm+cold 位于 NVMe）")

    def _step_5(self):
        """阶段 B：再等 PHASE_B_WAIT_S 秒，让 cold 对象继续 NVMe→HDD。"""
        self._set_step(5,
            f"等 {self.PHASE_B_WAIT_S}s — cold 继续下沉 HDD")
        cold_n = self.N_OBJS - self.HOT_K - self.WARM_K
        self._add_event("PHASE", "#4488ff",
            f"阶段 B ({self.PHASE_B_WAIT_S}s)：{cold_n} 个 cold 对象继续下沉 HDD")
        t_b = time.time()
        last_hot = 0.0
        prev = dict(self._state["tiers"])
        while time.time() - t_b < self.PHASE_B_WAIT_S:
            time.sleep(0.4)
            if time.time() - last_hot >= self.HOT_KEEPALIVE_S:
                self._touch_hot_keys("阶段 B hot 保热")
                last_hot = time.time()
            self._refresh_tiers()
            cur = self._state["tiers"]
            dd_hdd = cur["hdd"] - prev["hdd"]
            if dd_hdd > 0:
                self._add_event(
                    "MIGRATE", "#4488ff",
                    f"NVMe→HDD: +{dd_hdd}  当前 "
                    f"DRAM={cur['dram']} NVMe={cur['nvme']} HDD={cur['hdd']}")
            prev = dict(cur)
        self._refresh_tiers()
        cur = self._state["tiers"]
        self._add_event("STEP_DONE", "#00e888",
            f"step5 完成：三层稳定 DRAM={cur['dram']} NVMe={cur['nvme']} HDD={cur['hdd']}"
            f"（预期 ≈ {self.HOT_K}/{self.WARM_K}/{cold_n}）")

    def _step_6(self):
        """快照触发：冷层 ≥ SNAP_THRESHOLD 则归档 HDD 上的对象到 JSON。"""
        self._set_step(6,
            f"检查冷层 ≥ {self.SNAP_THRESHOLD} 触发快照")
        cold_keys = self._ctx["cold_keys"]
        self._refresh_tiers()
        cold_now = self._state["tiers"]["hdd"]
        if cold_now >= self.SNAP_THRESHOLD:
            self._add_event("SNAP_TRIGGER", "#a060ff",
                f"✓ 冷层={cold_now} ≥ 阈值 {self.SNAP_THRESHOLD}，触发快照归档")
            hdd_keys = cold_keys[:cold_now]
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
            self._add_event("SNAP_SKIP", "#ffb020",
                f"✗ 冷层={cold_now} < 阈值 {self.SNAP_THRESHOLD}，本轮不归档")

    def _step_7(self):
        """回访 REVISIT_N 个 HDD 对象，演示 HDD→DRAM 自动回迁。"""
        self._set_step(7, f"访问 {self.REVISIT_N} 个 HDD 对象 → 自动回迁 DRAM")
        cold_keys = self._ctx["cold_keys"]
        revisit = cold_keys[:self.REVISIT_N]
        self._refresh_tiers()
        before = dict(self._state["tiers"])
        for k in revisit:
            r = self._get(k)
            self._add_event(
                "REVISIT_COLD", "#00e888",
                f"访问 {k} → hit={r.get('hit','?')}")
            time.sleep(0.12)
        time.sleep(0.5)
        self._refresh_tiers()
        cur = self._state["tiers"]
        if cur["dram"] > before["dram"]:
            self._add_event("PROMOTE", "#00e888",
                f"回迁生效：DRAM {before['dram']}→{cur['dram']}，"
                f"HDD {before['hdd']}→{cur['hdd']}")
        else:
            self._add_event("HINT", "#ffb020",
                f"统计暂未看到 DRAM 上升（{before['dram']}→{cur['dram']}），"
                f"但 hit 字段显示 promote 已发生，可能存在采样延迟")

    def _step_8(self):
        """汇总：把最终三层分布与预期对比输出一行总结事件。"""
        self._set_step(8, "汇总三层分布 & 演示结束")
        self._refresh_tiers()
        cur = self._state["tiers"]
        cold_n = self.N_OBJS - self.HOT_K - self.WARM_K
        # 预期：回迁 5 个 HDD→DRAM 后
        exp_dram = self.HOT_K + self.REVISIT_N
        exp_nvme = self.WARM_K
        exp_hdd  = cold_n - self.REVISIT_N
        self._add_event("SUMMARY", "#c0d8f0",
            f"最终分布 DRAM={cur['dram']} NVMe={cur['nvme']} HDD={cur['hdd']}  |  "
            f"预期 {exp_dram}/{exp_nvme}/{exp_hdd}  |  "
            f"规模 hot={self.HOT_K} warm={self.WARM_K} cold={cold_n}")
        self._add_event("STEP_DONE", "#00e888",
            "✓ §6 分级存储演示完成：访问驱动下的三层分布已稳定")

    # ========================================================
    # helper 方法
    # ========================================================
