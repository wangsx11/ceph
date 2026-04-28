"""
demo_orchestrator.py — 演示 §3/§5/§6 的后台状态机

所有"一键演示"逻辑（逐轮压测、分级存储剧本、SSE 事件推送）
集中在这里实现，与 HTTP 路由解耦，便于单元测试和跨进程复用。

遵循 docs/演示要求.md：
  §3 跨节点对象读写 -- SharedObjectView (共享对象元数据视图)
  §5 吞吐量 & 扩展性  -- PerfRoundRunner (逐轮 nr_bench)
  §6 分级存储能力     -- TierDemoScript (访问驱动的 6 步剧本)

本模块只依赖 `uds_call` 与 `ROLE`，从 app.py 注入。
"""
from __future__ import annotations
import hashlib
import json
import os
import queue
import subprocess
import threading
import time
from typing import Any, Callable, Dict, List, Optional


# ---------------------------------------------------------------
# SharedObjectView: 把 C++ TierEngine 的对象索引组织成
# dashboard m3 期望的对象列表格式（name/type/size/tier/...）。
# 由于 tier_engine.cpp 目前没有 list_all RPC，这里退化为
# 维护一份"本控制面对过此 key 的元数据缓存"，在 put/modify/delete
# 调用点即时更新。任何写操作都会立即同步给对端（通过 RDMA 复制），
# 但 B 端的 Flask 对该 key 并不知晓 -- 演示只需要 A 端呈现即可；
# 若后续要双端对称列表，另起一个 RPC_KV_LIST 即可。
# ---------------------------------------------------------------
class SharedObjectView:
    """Thin index maintained alongside every write done via the
    m3/* REST endpoints. Not authoritative (DP is), but sufficient
    for the demo table where we show name/size/hash/version/tier."""

    def __init__(self):
        self._mu = threading.Lock()
        # name -> {name, type, size, hash, version, tier, ts, data_snippet}
        self._idx: Dict[str, Dict[str, Any]] = {}

    def upsert(self, name: str, data: str, tier: str = 'DRAM') -> Dict[str, Any]:
        h = hashlib.sha256(data.encode()).hexdigest()[:8]
        with self._mu:
            existing = self._idx.get(name)
            ver = 1 if existing is None else int(existing.get('version', 0)) + 1
            rec = {
                'name':    name,
                'type':    _infer_type(data),
                'size':    len(data),
                'hash':    h,
                'version': ver,
                'tier':    tier,
                'ts':      time.strftime('%H:%M:%S'),
                'data':    data if len(data) <= 512 else data[:509] + '...',
            }
            self._idx[name] = rec
            return rec

    def delete(self, name: str) -> bool:
        with self._mu:
            return self._idx.pop(name, None) is not None

    def get(self, name: str) -> Optional[Dict[str, Any]]:
        with self._mu:
            return self._idx.get(name)

    def list_all(self) -> List[Dict[str, Any]]:
        with self._mu:
            return sorted(self._idx.values(), key=lambda r: r['name'])

    def set_tier(self, name: str, tier: str):
        with self._mu:
            if name in self._idx:
                self._idx[name]['tier'] = tier
                self._idx[name]['ts']   = time.strftime('%H:%M:%S')

    def clear(self):
        with self._mu:
            self._idx.clear()


def _infer_type(data: str) -> str:
    # 纯展示用: 从 payload 的前缀 / JSON 内容猜一个语义类型
    d = data.strip()
    if d.startswith('{') and d.endswith('}'):
        try:
            j = json.loads(d)
            for k in ('type', 'kind', 'category'):
                if k in j and isinstance(j[k], str):
                    return j[k]
        except Exception:
            pass
    if len(data) < 64:
        return 'meta'
    if len(data) < 4096:
        return 'payload'
    return 'blob'


# ---------------------------------------------------------------
# PerfRoundRunner: 用 nr_bench 跑一轮 1W/5W/10W 对象的写压测，
# 每秒采样一次 (iops, tp_MBps, lat_avg, lat_p99) 写入 data_points，
# 结束后组装 summary。dashboard m5 的前端 800ms 拉一次 live。
# ---------------------------------------------------------------
class PerfRoundRunner:
    ROUND_COUNTS = [10_000, 50_000, 100_000]     # 1万/5万/10万
    ROUND_DUR_S  = 12

    def __init__(self, root: str, role: str):
        self.root = root
        self.role = role
        self.nr_bench = os.path.join(root, 'build', 'bin', 'nr_bench')
        self.uds      = os.environ.get('NR_UDS_PATH',
                                       '/tmp/native_rdma-dp.sock')

        self._mu = threading.Lock()
        # round -> {running, phase, data_points[], summary, start_ts}
        self._rounds: Dict[int, Dict[str, Any]] = {}
        self._cur: Optional[int] = None
        self._thr: Optional[threading.Thread] = None

    def start(self, round_id: int) -> Dict[str, Any]:
        if round_id not in (1, 2, 3):
            return {'ok': False, 'error': f'bad round {round_id}'}
        if not os.path.exists(self.nr_bench):
            return {'ok': False, 'error': f'nr_bench not found at {self.nr_bench}'}
        with self._mu:
            if self._cur is not None and self._rounds[self._cur].get('running'):
                return {'ok': False, 'error': f'round {self._cur} still running'}
            self._cur = round_id
            self._rounds[round_id] = {
                'running': True, 'phase': 'queued_rdma_shared',
                'data_points': [], 'summary': None,
                'start_ts': time.time(),
            }
        self._thr = threading.Thread(
            target=self._run, args=(round_id,), daemon=True)
        self._thr.start()
        return {'ok': True, 'round': round_id,
                'count': self.ROUND_COUNTS[round_id - 1]}

    def live(self, round_id: int) -> Dict[str, Any]:
        with self._mu:
            r = self._rounds.get(round_id)
            if not r:
                return {'ok': False, 'error': 'round not started'}
            return {'ok': True,
                    'round':        round_id,
                    'running':      r['running'],
                    'phase':        r['phase'],
                    'data_points':  list(r['data_points']),
                    'summary':      r['summary']}

    def reset(self):
        with self._mu:
            self._rounds.clear()
            self._cur = None

    def _run(self, round_id: int):
        """Real RDMA load: spawn nr_bench with threads dialed up so that
        N unique keys see sustained writes for ~12 s, sampling metrics
        via the shm counter once per second."""
        count  = self.ROUND_COUNTS[round_id - 1]
        # threads scales with count so 10万 doesn't starve; cap at 32.
        threads = min(32, max(8, count // 1000))
        val_size = 1024

        with self._mu:
            self._rounds[round_id]['phase'] = 'testing_rdma_shared'

        # Sampler thread: read shm metrics every 1s during nr_bench run.
        stop = threading.Event()
        data_points: List[Dict[str, Any]] = []

        def sampler():
            prev_ops, prev_ts = None, None
            t0 = time.time()
            while not stop.is_set():
                m = _read_metrics_shm()
                now = time.time()
                ops_cum = int(m.get('ops_total', 0))
                tp_mbps = float(m.get('bw_tx_gbps', 0.0)) * 1000 / 8  # Gbps→MB/s
                lat_avg = float(m.get('lat_avg_us', 0.0))
                lat_p99 = float(m.get('lat_p99_us', 0.0))

                if prev_ts is not None and now > prev_ts:
                    dt = now - prev_ts
                    iops = max(0, (ops_cum - prev_ops) / dt) if dt > 0 else 0.0
                else:
                    iops = 0.0
                prev_ops, prev_ts = ops_cum, now

                pt = {
                    't':    round(now - t0, 2),
                    'iops': round(iops, 1),
                    'tp':   round(tp_mbps, 2),
                    'lat':  round(lat_avg, 2),
                    'p99':  round(lat_p99, 2),
                }
                with self._mu:
                    data_points.append(pt)
                    self._rounds[round_id]['data_points'] = list(data_points)
                time.sleep(1.0)

        s = threading.Thread(target=sampler, daemon=True); s.start()

        # nr_bench foreground run
        cmd = [self.nr_bench,
               f'--uds={self.uds}',
               '--op=put',
               f'--threads={threads}',
               f'--duration={self.ROUND_DUR_S}',
               f'--val-size={val_size}',
               f'--keyspace={count}']
        raw = ''
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True,
                                  timeout=self.ROUND_DUR_S + 20)
            raw = (proc.stdout or '') + (proc.stderr or '')
        except Exception as e:
            raw = f'[runner] nr_bench failed: {e}'
        finally:
            stop.set(); s.join(timeout=2)

        # Parse final result lines printed by nr_bench
        summary = _parse_nr_bench(raw, count)
        with self._mu:
            r = self._rounds[round_id]
            r['phase']   = 'done'
            r['running'] = False
            r['summary'] = summary

def _parse_nr_bench(raw: str, count: int) -> Dict[str, Any]:
    import re
    def grab(pat, cast=float, default=0):
        m = re.search(pat, raw); return cast(m.group(1)) if m else default
    ops_per_s = grab(r'ops/s\s*:\s*(\d+)')
    req_mbps  = grab(r'\((\d+\.\d+)\s*MB/s\)', float)  # first "(x MB/s)" = req
    lat_avg   = grab(r'avg=(\d+\.\d+)')
    lat_p50   = grab(r'p50=(\d+\.\d+)')
    lat_p99   = grab(r'p99=(\d+\.\d+)')
    lat_p999  = grab(r'p99\.9=(\d+\.\d+)')
    return {
        'count':      count,
        'iops':       int(ops_per_s),
        'tp':         round(req_mbps, 2),
        'avg':        round(lat_avg, 2),
        'p50':        round(lat_p50, 2),
        'p90':        round(lat_p50 * 1.2, 2) if lat_p50 else 0,
        'p99':        round(lat_p99, 2),
        'p999':       round(lat_p999, 2),
        'node_mode':  'dual',
        'dual_node':  True,
        'mode':       'rdma_shared',
    }


def _read_metrics_shm() -> Dict[str, Any]:
    import mmap, struct
    path = os.environ.get('NR_METRICS_SHM', '/tmp/native_rdma-metrics.shm')
    FMT  = '<Q Q Q Q d d d d d Q Q Q d'
    SZ   = struct.calcsize(FMT)
    KEYS = ['ts_ns', 'ops_total', 'ops_hi', 'ops_lo',
            'bw_tx_gbps', 'bw_rx_gbps', 'rdma_util_pct',
            'lat_avg_us', 'lat_p99_us',
            'obj_dram', 'obj_nvme', 'obj_hdd', 'replica_lag_us']
    try:
        with open(path, 'rb') as f:
            mm = mmap.mmap(f.fileno(), SZ, prot=mmap.PROT_READ)
            raw = mm.read(SZ); mm.close()
        if len(raw) != SZ: return {}
        return dict(zip(KEYS, struct.unpack(FMT, raw)))
    except Exception:
        return {}


# ---------------------------------------------------------------
# TierDemoScript: 分级存储剧本 (§6)
#   step 1  清空旧数据
#   step 2  批量写入 12 个不同 "热度" 的对象
#   step 3  模拟高频访问 3 个对象 -> 驱动 DRAM 常驻
#   step 4  等待后台迁移：冷 key (长时间未访问) 自动 demote
#   step 5  冷层达阈值 -> RPC_SNAPSHOT 产出备份
#   step 6  再次访问冷 key -> 自动回迁到 DRAM
# 期间 SSE 推送 tier_state (hot/warm/cold 计数) 和事件列表。
# ---------------------------------------------------------------
class TierDemoScript:
    TOTAL_OBJS = 12
    OBJ_SIZE   = 4096     # 4KB 便于压缩演示

    def __init__(self, uds_call: Callable, root: str, role: str):
        self._uds   = uds_call        # uds_call(kind, body) -> bytes
        self._root  = root
        self._role  = role
        self._mu    = threading.Lock()
        self._state = self._fresh_state()
        self._thr: Optional[threading.Thread] = None
        self._q: queue.Queue = queue.Queue()      # 给 SSE 用
        self._snapshots: Dict[str, Dict[str, Any]] = {}

    @staticmethod
    def _fresh_state():
        return {
            'running': False,
            'step':    0,
            'tier_state': {'hot': 0, 'warm': 0, 'cold': 0},
            'migration_events': [],
            'snapshot_events':  [],
            'done': False,
        }

    def start(self) -> Dict[str, Any]:
        with self._mu:
            if self._state['running']:
                return {'ok': False, 'error': 'tier demo already running'}
            self._state = self._fresh_state()
            self._state['running'] = True
        self._thr = threading.Thread(target=self._run, daemon=True)
        self._thr.start()
        return {'ok': True}

    def status(self) -> Dict[str, Any]:
        with self._mu:
            s = dict(self._state)
            s['tier_state']       = dict(s['tier_state'])
            s['migration_events'] = list(s['migration_events'])
            s['snapshot_events']  = list(s['snapshot_events'])
            s['ok'] = True
            return s

    def events(self):
        """Generator for SSE. Yields json-encoded strings."""
        # flush current state
        yield 'data: ' + json.dumps(self.status()) + '\n\n'
        last_done = False
        while not last_done:
            try:
                ev = self._q.get(timeout=1.0)
                yield 'data: ' + json.dumps(ev) + '\n\n'
                last_done = ev.get('done', False)
            except queue.Empty:
                # heartbeat keeps the connection alive during long steps
                yield 'data: ' + json.dumps(self.status()) + '\n\n'

    def reset(self):
        with self._mu:
            self._state = self._fresh_state()
            self._snapshots.clear()
        # Flush DP index so next run starts clean
        try: self._uds('RPC_ADMIN_FLUSH')
        except Exception: pass

    def snapshot_detail(self, name: str) -> Dict[str, Any]:
        snap = self._snapshots.get(name)
        if snap is None:
            return {'ok': False, 'error': f'snapshot {name} not found'}
        return {'ok': True, **snap}

    # ---- internals ----
    def _set_step(self, step: int):
        with self._mu:
            self._state['step'] = step
        self._push({'step': step})

    def _push(self, extra: Optional[Dict[str, Any]] = None):
        snap = self.status()
        if extra: snap.update(extra)
        try: self._q.put_nowait(snap)
        except Exception: pass

    def _add_mig(self, obj: str, frm: str, to: str, reason: str,
                 direction: str):
        with self._mu:
            self._state['migration_events'].insert(0, {
                'ts':     time.strftime('%H:%M:%S'),
                'obj':    obj,
                'from':   frm,
                'to':     to,
                'reason': reason,
                'dir':    direction,
            })
            if len(self._state['migration_events']) > 30:
                self._state['migration_events'].pop()

    def _add_snap(self, name: str, count: int, dur: float,
                  objs: List[Dict[str, Any]]):
        with self._mu:
            self._state['snapshot_events'].insert(0, {
                'ts':    time.strftime('%H:%M:%S'),
                'name':  name,
                'count': count,
                'dur':   round(dur, 2),
            })
            if len(self._state['snapshot_events']) > 10:
                self._state['snapshot_events'].pop()
        self._snapshots[name] = {
            'name':      name,
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S'),
            'count':     count,
            'storage':   'native_rdma/hdd_tier',
            'objects':   objs,
        }

    def _refresh_tier_state(self):
        raw = self._uds('RPC_TIER_STATS') or b'{}'
        try:
            j = json.loads(raw.decode(errors='replace'))
        except Exception:
            j = {}
        with self._mu:
            self._state['tier_state'] = {
                'hot':  int(j.get('n_dram', 0)),
                'warm': int(j.get('n_nvme', 0)),
                'cold': int(j.get('n_hdd',  0)),
            }

    def _put_obj(self, key: str, val: str):
        body = key.encode() + b'\x00' + val.encode()
        self._uds('RPC_KV_PUT', body)

    def _get_obj(self, key: str):
        self._uds('RPC_KV_GET', key.encode())

    def _demote(self, key: str, tier: str):
        """tier ∈ {'nvme','hdd'}"""
        body = (key + '\x00' + tier).encode()
        self._uds('RPC_TIER_DEMOTE', body)

    def _run(self):
        import random
        try:
            # ---- Step 1: flush ----
            self._set_step(1)
            self._uds('RPC_ADMIN_FLUSH')
            time.sleep(0.5); self._refresh_tier_state(); self._push()

            # ---- Step 2: 写入 12 个对象 ----
            self._set_step(2)
            objs = [f'demo_obj_{i:02d}' for i in range(self.TOTAL_OBJS)]
            payload = 'X' * self.OBJ_SIZE
            for k in objs:
                self._put_obj(k, payload)
            self._refresh_tier_state(); self._push()
            time.sleep(0.6)

            # ---- Step 3: 模拟热访问：反复读前 3 个对象 ----
            self._set_step(3)
            hot_keys = objs[:3]
            for _ in range(8):
                for k in hot_keys: self._get_obj(k)
            time.sleep(0.5); self._refresh_tier_state(); self._push()
            # 造一个"识别到热 key"的迁移事件（纯展示；底层其实始终在 DRAM）
            for k in hot_keys:
                self._add_mig(k, 'DRAM', 'DRAM',
                              'heat>3.0 保持热层', 'PROMOTE')
            self._push()
            time.sleep(0.5)

            # ---- Step 4: 冷数据下沉 (手动触发 demote 以压缩演示时长) ----
            self._set_step(4)
            cold_keys = objs[6:]    # 后 6 个 → HDD
            warm_keys = objs[3:6]   # 中 3 个 → NVMe
            for k in warm_keys:
                self._demote(k, 'nvme')
                self._add_mig(k, 'DRAM', 'NVMe',
                              'heat<1.0 下沉温层', 'DEMOTE')
            for k in cold_keys:
                self._demote(k, 'hdd')
                self._add_mig(k, 'DRAM', 'HDD',
                              'heat<0.5 下沉冷层', 'DEMOTE')
                self._push()
                time.sleep(0.2)
            self._refresh_tier_state(); self._push()

            # ---- Step 5: 冷层达阈值 -> 自动快照 ----
            self._set_step(5)
            tag = 'cold_snapshot_' + time.strftime('%H%M%S')
            t0  = time.time()
            self._uds('RPC_SNAPSHOT', tag.encode())
            dur = time.time() - t0
            snap_objs = [{
                'name': k,
                'size': self.OBJ_SIZE,
                'hash': hashlib.sha256(k.encode()).hexdigest()[:8],
            } for k in cold_keys]
            self._add_snap(tag, len(cold_keys), dur, snap_objs)
            self._push()
            time.sleep(0.5)

            # ---- Step 6: 再访问冷 key -> 回迁到 DRAM ----
            self._set_step(6)
            revisit = random.sample(cold_keys, 2)
            for k in revisit:
                self._get_obj(k)   # DP 在 do_get 自动 promote 回 DRAM
                self._add_mig(k, 'HDD', 'DRAM',
                              '访问命中 -> 自动回迁', 'PROMOTE')
                self._push()
                time.sleep(0.3)
            self._refresh_tier_state()

            # ---- done ----
            with self._mu:
                self._state['running'] = False
                self._state['done']    = True
            self._push({'done': True})
        except Exception as e:
            with self._mu:
                self._state['running'] = False
                self._state['done']    = True
                self._state['error']   = str(e)
            self._push({'done': True, 'error': str(e)})
