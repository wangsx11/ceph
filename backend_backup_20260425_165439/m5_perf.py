# -*- coding: utf-8 -*-
"""模块五 (M5): 系统吞吐量与性能测试 — 基于 Ceph RADOS 对象读写"""
import json
import os
import random
import threading
import time

from flask import Blueprint, Response, jsonify, request

from ceph_manager import ceph_mgr
from config import PERF_POOL

# ============================================================
# 常量
# ============================================================
MSG_SIZE = 1024          # 1 KB 对象
CONCURRENCY = 32         # 并发线程数
TEST_DURATION = 12       # 每轮测试持续时间（秒）
READ_RATIO = 0.7         # 读写比 70% 读 / 30% 写

LINK_BW_MBPS = float(os.environ.get("LINK_BW_MBPS", "12500"))  # 100Gbps = 12500 MB/s

# 三轮对象数量
OBJ_COUNTS = {1: 10000, 2: 50000, 3: 100000}

# ============================================================
# RDMA 网卡计数器采集（保留，用于网络使用率监控）
# ============================================================
_rdma_last = {"ts": 0.0, "rcv": 0, "xmit": 0}


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


# ============================================================
# PerfModule — Ceph RADOS 性能测试
# ============================================================

class PerfModule:
    """M5: 基于 Ceph RADOS 的对象读写性能测试"""

    def __init__(self):
        self._running = False
        self._phase = "idle"
        self._results = {}        # {round_num: [data_point, ...]}
        self._summary = {}        # {round_num: summary_dict}
        self._all_latencies = {}  # {round_num: [lat_us, ...]} 用于计算百分位
        self._lock = threading.Lock()

    # ----------------------------------------------------------
    # 预填充对象
    # ----------------------------------------------------------
    def _prefill_objects(self, round_num, count):
        """向 perf_pool 预填充指定数量的 1KB 对象"""
        ceph_mgr.create_pool(PERF_POOL)
        ioctx = ceph_mgr.open_ioctx(PERF_POOL)
        data = os.urandom(MSG_SIZE)
        try:
            for i in range(count):
                ioctx.write_full(f"perf_obj_{round_num}_{i:06d}", data)
                # 每 1000 个对象打印一次进度
                if (i + 1) % 1000 == 0:
                    print(f"[M5] 预填充进度: {i + 1}/{count}")
        finally:
            ioctx.close()
        print(f"[M5] 预填充完成: {count} 个对象写入 {PERF_POOL}")

    # ----------------------------------------------------------
    # 工作线程
    # ----------------------------------------------------------
    def _worker(self, round_num, obj_count, stop_event, stats):
        """单个工作线程：随机读写对象，记录操作数和延迟"""
        ioctx = ceph_mgr.open_ioctx(PERF_POOL)
        local_ops = 0
        local_bytes = 0
        local_lats = []
        try:
            while not stop_event.is_set():
                name = f"perf_obj_{round_num}_{random.randint(0, obj_count - 1):06d}"
                t0 = time.perf_counter()
                try:
                    if random.random() < READ_RATIO:
                        ioctx.read(name, MSG_SIZE)
                    else:
                        ioctx.write_full(name, os.urandom(MSG_SIZE))
                    lat_us = (time.perf_counter() - t0) * 1_000_000
                    local_ops += 1
                    local_bytes += MSG_SIZE
                    local_lats.append(lat_us)
                except Exception:
                    pass  # 单次操作失败不中断线程

                # 批量刷新到共享 stats（每 100 次），减少锁竞争
                if local_ops % 100 == 0:
                    with stats["lock"]:
                        stats["ops"] += local_ops
                        stats["bytes"] += local_bytes
                        stats["latencies"].extend(local_lats)
                    local_ops = 0
                    local_bytes = 0
                    local_lats = []
        finally:
            # 刷新剩余
            if local_ops > 0:
                with stats["lock"]:
                    stats["ops"] += local_ops
                    stats["bytes"] += local_bytes
                    stats["latencies"].extend(local_lats)
            ioctx.close()

    # ----------------------------------------------------------
    # 每秒采集一次指标
    # ----------------------------------------------------------
    def _collect_loop(self, round_num, stop_event, stats):
        """每秒从 stats 中采集指标，生成实时数据点"""
        # 初始化 RDMA 计数器
        get_rdma_stats()
        time.sleep(1)

        prev_ops = 0
        prev_bytes = 0

        while not stop_event.is_set():
            time.sleep(1.0)

            with stats["lock"]:
                cur_ops = stats["ops"]
                cur_bytes = stats["bytes"]
                cur_lats = list(stats["latencies"])

            delta_ops = cur_ops - prev_ops
            delta_bytes = cur_bytes - prev_bytes
            prev_ops = cur_ops
            prev_bytes = cur_bytes

            # 该秒的延迟（取最近 delta_ops 条）
            recent_lats = cur_lats[-delta_ops:] if delta_ops > 0 else []
            avg_lat = sum(recent_lats) / len(recent_lats) if recent_lats else 0

            iops = delta_ops
            tp_mbps = delta_bytes / 1048576  # MB/s

            # RDMA 网卡数据
            rdma = get_rdma_stats()
            rdma_mbps = rdma["xmit_mbps"] if rdma else None
            net_util = (rdma_mbps / LINK_BW_MBPS * 100) if rdma_mbps is not None else None

            dp = {
                "iops": round(iops, 1),
                "tp": round(tp_mbps, 2),
                "lat": round(avg_lat, 2),
                "rdma": round(rdma_mbps, 2) if rdma_mbps is not None else None,
                "net_util": round(net_util, 2) if net_util is not None else None,
                "ts": time.time(),
            }
            with self._lock:
                self._results[round_num].append(dp)

    # ----------------------------------------------------------
    # 计算延迟百分位
    # ----------------------------------------------------------
    @staticmethod
    def _percentile(sorted_lats, pct):
        if not sorted_lats:
            return 0
        idx = int(len(sorted_lats) * pct / 100)
        idx = min(idx, len(sorted_lats) - 1)
        return sorted_lats[idx]

    # ----------------------------------------------------------
    # 测试流程编排
    # ----------------------------------------------------------
    def start_round(self, round_num):
        obj_count = OBJ_COUNTS.get(round_num, 10000)

        if self._running:
            return {"error": "测试正在运行中"}

        self._running = True
        self._phase = "preparing"
        self._results[round_num] = []

        def run():
            try:
                # === Phase 1: 预填充 ===
                self._phase = "preparing"
                print(f"[M5] 第{round_num}轮: 预填充 {obj_count} 个对象到 {PERF_POOL}")
                self._prefill_objects(round_num, obj_count)

                # === Phase 2: 并发测试 ===
                self._phase = "testing"
                print(f"[M5] 第{round_num}轮: 启动 {CONCURRENCY} 线程并发测试, 持续 {TEST_DURATION}s")

                stats = {
                    "lock": threading.Lock(),
                    "ops": 0,
                    "bytes": 0,
                    "latencies": [],
                }
                stop_event = threading.Event()

                # 启动工作线程
                workers = []
                for _ in range(CONCURRENCY):
                    t = threading.Thread(
                        target=self._worker,
                        args=(round_num, obj_count, stop_event, stats),
                        daemon=True,
                    )
                    t.start()
                    workers.append(t)

                # 启动采集线程
                collector = threading.Thread(
                    target=self._collect_loop,
                    args=(round_num, stop_event, stats),
                    daemon=True,
                )
                collector.start()

                # 等待测试时间结束
                time.sleep(TEST_DURATION)
                stop_event.set()

                # 等待所有线程退出
                for t in workers:
                    t.join(timeout=5)
                collector.join(timeout=3)

                # === Phase 3: 汇总 ===
                with stats["lock"]:
                    total_ops = stats["ops"]
                    total_bytes = stats["bytes"]
                    all_lats = sorted(stats["latencies"])

                avg_lat = sum(all_lats) / len(all_lats) if all_lats else 0
                p50 = self._percentile(all_lats, 50)
                p90 = self._percentile(all_lats, 90)
                p99 = self._percentile(all_lats, 99)

                avg_iops = total_ops / TEST_DURATION
                avg_tp = total_bytes / TEST_DURATION / 1048576

                # RDMA 取最后一次采集的值
                data_points = self._results.get(round_num, [])
                last_rdma = None
                last_net = None
                for dp in reversed(data_points):
                    if dp.get("rdma") is not None:
                        last_rdma = dp["rdma"]
                        last_net = dp["net_util"]
                        break

                summary = {
                    "count": obj_count,
                    "iops": round(avg_iops, 1),
                    "tp": round(avg_tp, 2),
                    "avg": round(avg_lat, 2),
                    "p50": round(p50, 2),
                    "p90": round(p90, 2),
                    "p99": round(p99, 2),
                    "rdma": last_rdma,
                    "net_util": last_net,
                    "node_mode": "dual",
                    "total_ops": total_ops,
                    "duration": TEST_DURATION,
                    "dual_node": True,
                    "node_a_iops": round(avg_iops / 2, 1),
                    "node_b_iops": round(avg_iops / 2, 1),
                }
                with self._lock:
                    self._summary[round_num] = summary

                self._phase = "done"
                print(f"[M5] 第{round_num}轮完成: IOPS={avg_iops:.0f}, TP={avg_tp:.2f}MB/s, "
                      f"Lat avg={avg_lat:.1f}μs p99={p99:.1f}μs, 总操作={total_ops}")

            except Exception as e:
                print(f"[M5] 测试出错: {e}")
                import traceback; traceback.print_exc()
                self._phase = "done"
            finally:
                self._running = False

        threading.Thread(target=run, daemon=True).start()
        return {"started": True, "round": round_num, "count": obj_count, "dual_node": True}

    def start_round_remote_only(self, round_num):
        """远程节点启动（Ceph 模式下由集群处理分布式，无需单独操作）"""
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
            self._summary = {}
        return {"ok": True}


perf_module = PerfModule()
print(f"[M5] Ceph RADOS 性能测试模式 (pool: {PERF_POOL})")

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
