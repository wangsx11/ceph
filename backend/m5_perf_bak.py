# -*- coding: utf-8 -*-
"""模块五 (M5): 系统吞吐量与性能测试 — 简洁线程模型"""
import json
import os
import random
import subprocess
import threading
import time

from flask import Blueprint, Response, jsonify, request

from mock import USE_MOCK

if not USE_MOCK:
    from ceph_manager import ceph_mgr
    from config import PERF_POOL, RDMA_LINK_BANDWIDTH_GBPS
else:
    from mock.m5_mock import MockPerfModule

# 模块级 RDMA 计数器状态
_rdma_last = {"ts": 0.0, "rcv": 0, "xmit": 0}

# 64 KB 对象：吞吐量表现最佳（~900+ MB/s），RDMA 数据充实
OBJ_SIZE = 64 * 1024


def get_rdma_stats():
    """读取 InfiniBand 计数器差值，返回 MB/s 或 None"""
    global _rdma_last
    try:
        rdma_path = "/sys/class/infiniband"
        if not os.path.exists(rdma_path):
            return None
        devs = os.listdir(rdma_path)
        if not devs:
            return None
        dev = devs[0]
        rcv_file = f"{rdma_path}/{dev}/ports/1/counters/port_rcv_data"
        xmit_file = f"{rdma_path}/{dev}/ports/1/counters/port_xmit_data"
        if not os.path.exists(rcv_file):
            return None
        with open(rcv_file) as f:
            curr_rcv = int(f.read().strip()) * 4
        with open(xmit_file) as f:
            curr_xmit = int(f.read().strip()) * 4
    except Exception:
        return None

    now = time.time()
    if _rdma_last["ts"] == 0.0:
        _rdma_last.update({"ts": now, "rcv": curr_rcv, "xmit": curr_xmit})
        return None
    delta_t = now - _rdma_last["ts"]
    if delta_t < 0.1:
        return None

    rcv_mbps = (curr_rcv - _rdma_last["rcv"]) / delta_t / 1048576
    xmit_mbps = (curr_xmit - _rdma_last["xmit"]) / delta_t / 1048576
    _rdma_last.update({"ts": now, "rcv": curr_rcv, "xmit": curr_xmit})
    return {"rcv_mbps": round(rcv_mbps, 2), "xmit_mbps": round(xmit_mbps, 2)}


class PerfModule:
    """M5: 双节点并行性能测试 — 简洁线程模型"""

    def __init__(self):
        self.pool_name = PERF_POOL
        self._ioctx = None
        self._running = False
        self._results = {}
        self._results_b = {}
        self._summary = {}
        self._node_mode = {}
        self._lock = threading.Lock()

        self.remote_host = os.environ.get("REMOTE_HOST", "10.26.42.225")
        self.remote_user = os.environ.get("REMOTE_USER", "wangshouxin")
        self.current_node = os.environ.get("CURRENT_NODE", "A")

    # ----------------------------------------------------------
    # 远程节点通信
    # ----------------------------------------------------------
    def _run_remote_command(self, cmd):
        ssh_cmd = [
            "ssh", "-o", "StrictHostKeyChecking=no",
            f"{self.remote_user}@{self.remote_host}", cmd
        ]
        try:
            result = subprocess.run(ssh_cmd, capture_output=True, text=True, timeout=300)
            return result.returncode == 0, result.stdout, result.stderr
        except Exception as e:
            return False, "", str(e)

    def _start_remote_benchmark(self, round_num, obj_count, duration, concurrency):
        remote_cmd = (
            f"cd ~/ceph-web/backend && "
            f"PYTHONPATH=. python3 -c \""
            f"import sys; sys.path.insert(0, '.'); "
            f"from m5_perf import perf_module; "
            f"perf_module.start_remote_round({round_num}, {obj_count}, {duration}, {concurrency})"
            f"\""
        )
        return self._run_remote_command(remote_cmd)

    def start_remote_round(self, round_num, obj_count, duration, concurrency):
        if self._running:
            return {"error": "测试正在运行中"}
        self._running = True
        self._phase = "testing"
        self._results_b[round_num] = []

        def run():
            try:
                self._run_benchmark(round_num, obj_count, duration, concurrency, store_key="results_b")
            finally:
                self._running = False

        threading.Thread(target=run, daemon=True).start()
        return {"started": True}

    # ----------------------------------------------------------
    # 辅助方法
    # ----------------------------------------------------------
    def _get_ioctx(self):
        if self._ioctx is None:
            ceph_mgr.create_pool(self.pool_name)
            self._ioctx = ceph_mgr.open_ioctx(self.pool_name)
        return self._ioctx

    def _prepare_objects(self, count):
        """预填充对象"""
        pre_data = os.urandom(OBJ_SIZE)
        ceph_mgr.init()
        ceph_mgr.create_pool(self.pool_name)

        def write_batch(start, end):
            ioctx_local = ceph_mgr.open_ioctx(self.pool_name)
            for i in range(start, end):
                ioctx_local.write_full(f"bench_{i:08d}", pre_data)
            ioctx_local.close()

        num_threads = 16
        chunk = count // num_threads
        threads = []
        for t in range(num_threads):
            s = t * chunk
            e = s + chunk if t < num_threads - 1 else count
            th = threading.Thread(target=write_batch, args=(s, e))
            threads.append(th)
            th.start()
        for th in threads:
            th.join()

    # ----------------------------------------------------------
    # 核心基准测试：简洁同步线程模型
    # ----------------------------------------------------------
    def _run_benchmark(self, round_num, obj_count, duration=12, concurrency=32, store_key=None):
        if store_key is None:
            store_key = 'results'

        with self._lock:
            getattr(self, f'_{store_key}')[round_num] = []

        pre_data = os.urandom(OBJ_SIZE)
        read_ratio = 0.7
        stop_time = time.time() + duration

        ceph_mgr.init()

        # 共享区间统计（每秒重置一次）
        stats_lock = threading.Lock()
        iv = {'ops': 0, 'bytes': 0, 'sum_lat': 0.0, 'cnt': 0}
        all_lats = []
        total_ops = 0

        def worker():
            ioctx = ceph_mgr.open_ioctx(self.pool_name)
            loc_ops = 0
            loc_bytes = 0
            loc_sum_lat = 0.0
            loc_lats = []

            while time.time() < stop_time and self._running:
                key = f"bench_{random.randint(0, obj_count - 1):08d}"
                t0 = time.time()
                try:
                    if random.random() < read_ratio:
                        data = ioctx.read(key, OBJ_SIZE)
                        sz = len(data) if data else 0
                    else:
                        ioctx.write_full(key, pre_data)
                        sz = OBJ_SIZE
                    lat = (time.time() - t0) * 1000
                except Exception:
                    lat = 0
                    sz = 0

                loc_ops += 1
                loc_bytes += sz
                loc_sum_lat += lat
                loc_lats.append(lat)

                # 线程本地 batch：每 200 次刷入共享状态
                if loc_ops >= 200:
                    with stats_lock:
                        iv['ops'] += loc_ops
                        iv['bytes'] += loc_bytes
                        iv['sum_lat'] += loc_sum_lat
                        iv['cnt'] += loc_ops
                        all_lats.extend(loc_lats)
                    loc_ops = 0
                    loc_bytes = 0
                    loc_sum_lat = 0.0
                    loc_lats = []

            # 最终刷入（不含任何 drain 阶段）
            if loc_ops > 0:
                with stats_lock:
                    iv['ops'] += loc_ops
                    iv['bytes'] += loc_bytes
                    iv['sum_lat'] += loc_sum_lat
                    iv['cnt'] += loc_ops
                    all_lats.extend(loc_lats)
            ioctx.close()

        # 启动工作线程
        threads = []
        for _ in range(concurrency):
            t = threading.Thread(target=worker, daemon=True)
            t.start()
            threads.append(t)

        # 每秒采集一个 data point
        interval_start = time.time()
        while time.time() < stop_time and self._running:
            time.sleep(1.0)
            with stats_lock:
                now = time.time()
                elapsed = now - interval_start
                if elapsed > 0.5 and iv['cnt'] > 0:
                    iops = iv['ops'] / elapsed
                    tp = iv['bytes'] / elapsed / (1024 * 1024)
                    avg_lat = iv['sum_lat'] / iv['cnt']

                    rdma = get_rdma_stats()
                    rdma_val = round(rdma["rcv_mbps"], 2) if rdma else None

                    dp = {
                        "iops": round(iops, 1),
                        "tp": round(tp, 2),
                        "lat": round(avg_lat, 2),
                        "rdma": rdma_val,
                        "rdma_real": rdma is not None,
                        "ts": now,
                    }
                    getattr(self, f'_{store_key}')[round_num].append(dp)

                    total_ops += iv['ops']
                    iv['ops'] = 0
                    iv['bytes'] = 0
                    iv['sum_lat'] = 0.0
                    iv['cnt'] = 0
                    interval_start = now

        for t in threads:
            t.join(timeout=5)

        # 构建 summary
        all_lats.sort()
        n = len(all_lats)
        data_points = getattr(self, f'_{store_key}')[round_num]
        rdma_vals = [d["rdma"] for d in data_points if d.get("rdma") is not None]

        summary = {
            "count": obj_count,
            "iops": round(sum(d["iops"] for d in data_points) / max(len(data_points), 1), 1),
            "tp": round(sum(d["tp"] for d in data_points) / max(len(data_points), 1), 2),
            "avg": round(sum(all_lats) / max(n, 1), 2),
            "p50": round(all_lats[int(n * 0.5)] if n else 0, 2),
            "p90": round(all_lats[int(n * 0.9)] if n else 0, 2),
            "p99": round(all_lats[int(n * 0.99)] if n else 0, 2),
            "rdma": round(sum(rdma_vals) / max(len(rdma_vals), 1), 2) if rdma_vals else None,
            "rdma_real": any(d.get("rdma_real", False) for d in data_points),
            "node_mode": "single",
            "total_ops": total_ops,
            "duration": duration,
            "dual_node": False,
        }
        with self._lock:
            self._summary[round_num] = summary

    # ----------------------------------------------------------
    # 测试流程编排
    # ----------------------------------------------------------
    def start_round(self, round_num):
        counts = {1: 10000, 2: 50000, 3: 100000}
        obj_count = counts.get(round_num, 10000)
        duration = 12
        concurrency = 32

        if self._running:
            return {"error": "测试正在运行中"}

        self._running = True
        self._phase = "preparing"
        self._results[round_num] = []
        self._results_b[round_num] = []
        is_coordinator = (self.current_node == 'A')

        def run():
            try:
                self._phase = "preparing"
                self._prepare_objects(obj_count)
                self._phase = "testing"

                if is_coordinator:
                    print(f"[M5] 启动双节点并行测试 (round={round_num})")
                    remote_started = False
                    import urllib.request
                    for attempt in range(3):
                        try:
                            url = f"http://{self.remote_host}:5000/api/m5/start_remote"
                            data = json.dumps({"round": round_num}).encode('utf-8')
                            req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})
                            with urllib.request.urlopen(req, timeout=10) as resp:
                                result = json.loads(resp.read().decode())
                                if result.get('started'):
                                    remote_started = True
                                    print(f"[M5] 远程节点B测试已启动")
                                    break
                                else:
                                    print(f"[M5] 远程节点未就绪(尝试{attempt+1}/3): {result.get('error', '未知')}")
                                    time.sleep(3)
                        except Exception as e:
                            print(f"[M5] 远程启动失败(尝试{attempt+1}/3): {e}")
                            time.sleep(3)
                    if not remote_started:
                        print(f"[M5] 远程节点启动失败，将使用单节点模式")

                    self._run_benchmark(round_num, obj_count, duration, concurrency, store_key='results')

                    if remote_started:
                        import urllib.request as _ur
                        wait_end = time.time() + duration + 15
                        while time.time() < wait_end:
                            time.sleep(2)
                            try:
                                url = f"http://{self.remote_host}:5000/api/m5/live?round={round_num}"
                                with _ur.urlopen(url, timeout=5) as resp:
                                    data = json.loads(resp.read().decode())
                                    if data.get('data_points') and len(data['data_points']) > 0:
                                        self._results_b[round_num] = data['data_points']
                                        break
                            except Exception:
                                pass
                        print(f"[M5] 远程节点结果: {len(self._results_b.get(round_num, []))} 条")
                        self._node_mode[round_num] = "dual" if self._results_b.get(round_num) else "single"
                    else:
                        self._results_b[round_num] = []
                        self._node_mode[round_num] = "single"
                    self._build_summary(round_num)
                else:
                    print(f"[M5] 节点B执行测试 (round={round_num})")
                    self._run_benchmark(round_num, obj_count, duration, concurrency, store_key='results_b')

                self._phase = "done"
            except Exception as e:
                print(f"[M5] 测试出错: {e}")
                import traceback; traceback.print_exc()
                self._phase = "done"
            finally:
                self._running = False

        threading.Thread(target=run, daemon=True).start()
        return {"started": True, "round": round_num, "count": obj_count, "dual_node": True}

    def start_round_remote_only(self, round_num):
        counts = {1: 10000, 2: 50000, 3: 100000}
        obj_count = counts.get(round_num, 10000)
        duration = 12
        concurrency = 32

        for _ in range(30):
            if not self._running:
                break
            time.sleep(0.5)
        if self._running:
            return {"error": "测试正在运行中"}

        self._running = True
        self._phase = "testing"
        self._results[round_num] = []

        def run():
            try:
                self._run_benchmark(round_num, obj_count, duration, concurrency, store_key='results')
                self._phase = "done"
            except Exception as e:
                print(f"[M5] 远程测试出错: {e}")
                self._phase = "done"
            finally:
                self._running = False

        threading.Thread(target=run, daemon=True).start()
        return {"started": True, "round": round_num, "remote": True}

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
                "phase": getattr(self, '_phase', 'idle'),
                "round": round_num,
                "data_points": list(self._results.get(round_num, [])),
                "summary": self._summary.get(round_num, None),
            }

    def _build_summary(self, round_num):
        results_a = self._results.get(round_num, [])
        results_b = self._results_b.get(round_num, [])
        node_mode = self._node_mode.get(round_num, "single")

        all_points = results_a + results_b
        if not all_points:
            return

        rdma_vals = [d["rdma"] for d in all_points if d.get("rdma") is not None]
        rdma_real = any(d.get("rdma_real", False) for d in all_points)

        if node_mode == "dual" and results_a and results_b:
            count = max(len(results_a), len(results_b))
            iops = (sum(d["iops"] for d in results_a) + sum(d["iops"] for d in results_b)) / max(count, 1)
            tp = (sum(d["tp"] for d in results_a) + sum(d["tp"] for d in results_b)) / max(count, 1)
            node_a_iops = round(sum(d["iops"] for d in results_a) / max(len(results_a), 1), 1)
            node_b_iops = round(sum(d["iops"] for d in results_b) / max(len(results_b), 1), 1)
            dual_node = True
        else:
            pts = results_a or results_b
            count = len(pts)
            iops = sum(d["iops"] for d in pts) / max(count, 1)
            tp = sum(d["tp"] for d in pts) / max(count, 1)
            node_a_iops = round(iops, 1)
            node_b_iops = None
            dual_node = False

        with self._lock:
            existing = self._summary.get(round_num, {})
            existing.update({
                "iops": round(iops, 1),
                "tp": round(tp, 2),
                "rdma": round(sum(rdma_vals) / len(rdma_vals), 2) if rdma_vals else None,
                "rdma_real": rdma_real,
                "node_mode": node_mode,
                "dual_node": dual_node,
                "node_a_iops": node_a_iops,
                "node_b_iops": node_b_iops,
            })
            self._summary[round_num] = existing

    def reset(self):
        if self._running:
            self._running = False
            time.sleep(2)
        with self._lock:
            self._results = {}
            self._summary = {}
            self._node_mode = {}
        try:
            ioctx = self._get_ioctx()
            for obj in ioctx.list_objects():
                if obj.key.startswith("bench_"):
                    ioctx.remove_object(obj.key)
        except Exception:
            pass
        return {"ok": True}


if USE_MOCK:
    perf_module = MockPerfModule()
    print("[M5] Mock 模式已启用")
else:
    perf_module = PerfModule()

# ============================================================
# Flask Blueprint
# ============================================================

m5_bp = Blueprint('m5', __name__)


@m5_bp.route('/api/m5/start', methods=['POST'])
def m5_start():
    body = request.json or {}
    round_num = body.get("round", 1)
    try:
        return jsonify({"ok": True, **perf_module.start_round(round_num)})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@m5_bp.route('/api/m5/start_remote', methods=['POST'])
def m5_start_remote():
    body = request.json or {}
    round_num = body.get("round", 1)
    try:
        return jsonify({"ok": True, **perf_module.start_round_remote_only(round_num)})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@m5_bp.route('/api/m5/status', methods=['GET'])
def m5_status():
    try:
        return jsonify({"ok": True, **perf_module.get_status()})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@m5_bp.route('/api/m5/live', methods=['GET'])
def m5_live():
    round_num = int(request.args.get("round", 1))
    try:
        return jsonify({"ok": True, **perf_module.get_live_data(round_num)})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@m5_bp.route('/api/m5/reset', methods=['POST'])
def m5_reset():
    try:
        return jsonify(perf_module.reset())
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@m5_bp.route('/api/m5/stream', methods=['GET'])
def m5_stream():
    round_num = int(request.args.get("round", 1))

    def generate():
        last_len = 0
        while True:
            data = perf_module.get_live_data(round_num)
            points = data.get("data_points", [])
            if len(points) > last_len:
                new_points = points[last_len:]
                last_len = len(points)
                yield f"data: {json.dumps({'running': data['running'], 'new_points': new_points, 'summary': data.get('summary')})}\n\n"
            if not data["running"] and len(points) > 0:
                yield f"data: {json.dumps({'done': True, 'summary': data.get('summary')})}\n\n"
                break
            time.sleep(0.8)

    return Response(generate(), mimetype='text/event-stream')
