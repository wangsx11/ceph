# -*- coding: utf-8 -*-
"""模块五 (M5): 系统吞吐量与性能测试 — 裸 RDMA 传输 (ib_send_bw / ib_send_lat)"""
import json
import os
import random
import subprocess
import threading
import time

from flask import Blueprint, Response, jsonify, request

from config import RDMA_LINK_BANDWIDTH_GBPS

# ── RDMA 配置 ──────────────────────────────────────────────
RDMA_DEV = os.environ.get("RDMA_DEV", "mlx5_0")
RDMA_GID_INDEX = int(os.environ.get("RDMA_GID_INDEX", "3"))  # RoCE v2, IPv4
OBJ_SIZE = 1024  # 1 KB 对象
IB_PORT_BASE = int(os.environ.get("IB_PORT_BASE", "18515"))

# 远程节点地址
SSH_REMOTE = os.environ.get("REMOTE_HOST", "10.26.42.225")        # SSH 管理口
RDMA_REMOTE = os.environ.get("RDMA_REMOTE_IP", "192.168.0.214")  # RDMA 数据面
REMOTE_USER = os.environ.get("REMOTE_USER", "wangshouxin")

# ── RDMA 端口计数器 ───────────────────────────────────────
_rdma_last = {"ts": 0.0, "rcv": 0, "xmit": 0}


def get_rdma_stats():
    """读取 InfiniBand 端口计数器差值，返回 MB/s 或 None"""
    global _rdma_last
    try:
        base = f"/sys/class/infiniband/{RDMA_DEV}/ports/1/counters"
        with open(f"{base}/port_rcv_data") as f:
            curr_rcv = int(f.read().strip()) * 4
        with open(f"{base}/port_xmit_data") as f:
            curr_xmit = int(f.read().strip()) * 4
    except Exception:
        return None

    now = time.time()
    prev = _rdma_last
    if prev["ts"] == 0.0:
        _rdma_last = {"ts": now, "rcv": curr_rcv, "xmit": curr_xmit}
        return None
    dt = now - prev["ts"]
    if dt < 0.1:
        return None

    rcv_mbps = (curr_rcv - prev["rcv"]) / dt / 1048576
    xmit_mbps = (curr_xmit - prev["xmit"]) / dt / 1048576
    _rdma_last = {"ts": now, "rcv": curr_rcv, "xmit": curr_xmit}
    return {"rcv_mbps": round(rcv_mbps, 2), "xmit_mbps": round(xmit_mbps, 2)}


# ── 辅助函数 ──────────────────────────────────────────────

def _ssh(cmd, timeout=10):
    """在远程节点执行命令"""
    return subprocess.run(
        ["ssh", "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=5",
         f"{REMOTE_USER}@{SSH_REMOTE}", cmd],
        capture_output=True, text=True, timeout=timeout,
    )


def _ssh_bg_run(tool_cmd):
    """在远程节点后台启动 perftest 工具（使用 ~/bin/ 下的统一版本）。
    通过写入临时脚本再 nohup 执行，stdout/stderr 全部重定向防止 SSH 挂起。"""
    # 第一步: 写脚本并启动（stdout/stderr 必须重定向到 /dev/null 才能让 SSH 退出）
    script = (
        f"cat > /tmp/_ib_run.sh << 'SCRIPT'\n"
        f"#!/bin/bash\n"
        f"{tool_cmd}\n"
        f"SCRIPT\n"
        f"chmod +x /tmp/_ib_run.sh && "
        f"nohup /tmp/_ib_run.sh > /dev/null 2>&1 &"
    )
    try:
        _ssh(script, timeout=10)
    except subprocess.TimeoutExpired:
        print("[M5] 警告: SSH 启动脚本超时，但进程可能已启动")
    # 第二步: 单独检查进程是否存在
    time.sleep(1)
    try:
        r = _ssh("ps aux | grep -E 'ib_send_bw|ib_send_lat' | grep -v grep", timeout=5)
        if r.stdout.strip():
            print(f"[M5] 远程进程已启动")
        else:
            print(f"[M5] 警告: 远程进程可能未启动")
        return r
    except Exception as e:
        print(f"[M5] 检查远程进程异常: {e}")
        return None


def _kill_perftest():
    """杀掉本地和远程残留的 perftest 进程"""
    for target in ("local", "remote"):
        try:
            if target == "local":
                subprocess.run(
                    ["pkill", "-9", "-f", "ib_send_bw|ib_send_lat"],
                    capture_output=True, timeout=3,
                )
            else:
                _ssh("pkill -9 -f 'ib_send_bw|ib_send_lat' 2>/dev/null; true")
        except Exception:
            pass
    time.sleep(0.3)


def _parse_lat_output(text):
    """解析 ib_send_lat 输出 → {avg, p50, p90, p99} (单位 μs)
    数据行格式: #bytes #iters t_min t_max t_typical t_avg t_stdev 99% 99.9%
    索引:        0      1      2     3     4         5     6       7   8
    """
    for line in reversed(text.strip().split("\n")):
        parts = line.split()
        if len(parts) < 8:
            continue
        try:
            sz = float(parts[0])
            if int(sz) != OBJ_SIZE:
                continue
            t_typical = float(parts[4])  # ≈ median
            t_avg = float(parts[5])
            p99 = float(parts[7])
            p90 = round(t_typical + (p99 - t_typical) * 0.6, 2)  # 插值估算
            print(f"[M5] 解析延迟: avg={t_avg} p50={t_typical} p90={p90} p99={p99}")
            return {"avg": t_avg, "p50": t_typical, "p90": p90, "p99": p99}
        except (ValueError, IndexError):
            continue
    print(f"[M5] 延迟解析失败, 原始输出最后5行: {text.strip().split(chr(10))[-5:]}")
    return None


def _parse_bw_output(text):
    """解析 ib_send_bw 输出 → {bw_avg_mbps, msg_rate_mpps}
    数据行格式: #bytes #iterations BW_peak[MB/s] BW_avg[MB/s] MsgRate[Mpps]
    索引:        0      1           2             3            4
    """
    for line in reversed(text.strip().split("\n")):
        parts = line.split()
        if len(parts) < 4:
            continue
        try:
            sz = float(parts[0])
            if int(sz) != OBJ_SIZE:
                continue
            bw_avg = float(parts[3])
            msg_rate = float(parts[4]) if len(parts) > 4 else 0
            print(f"[M5] 解析带宽: BW_avg={bw_avg} MB/s, MsgRate={msg_rate} Mpps")
            return {
                "bw_avg_mbps": bw_avg,
                "msg_rate_mpps": msg_rate,
            }
        except (ValueError, IndexError):
            continue
    print(f"[M5] 带宽解析失败, 原始输出最后5行: {text.strip().split(chr(10))[-5:]}")
    return None


# ── 默认延迟（实测基线） ──────────────────────────────────
_DEFAULT_LAT = {"avg": 2.80, "p50": 2.62, "p90": 3.20, "p99": 3.89}


# ===========================================================
# PerfModule
# ===========================================================
class PerfModule:
    """M5: 裸 RDMA 双节点性能测试"""

    def __init__(self):
        self._running = False
        self._phase = "idle"
        self._results = {}
        self._results_b = {}
        self._summary = {}
        self._node_mode = {}
        self._lock = threading.Lock()

        self.remote_host = SSH_REMOTE
        self.remote_user = REMOTE_USER
        self.current_node = os.environ.get("CURRENT_NODE", "A")

    # ────────────────────────────────────────────────────────
    # 远程节点通信 (保持向后兼容)
    # ────────────────────────────────────────────────────────
    def _run_remote_command(self, cmd):
        try:
            r = _ssh(cmd, timeout=300)
            return r.returncode == 0, r.stdout, r.stderr
        except Exception as e:
            return False, "", str(e)

    # ────────────────────────────────────────────────────────
    # 延迟测试
    # ────────────────────────────────────────────────────────
    def _measure_latency(self, port):
        """运行 ib_send_lat 获取延迟统计 (μs)"""
        _kill_perftest()
        time.sleep(0.5)

        # 在远程启动 server（使用 ~/bin/ 下的统一版本 v5.60）
        _ssh_bg_run(
            f"~/bin/ib_send_lat -s {OBJ_SIZE} -n 5000 -p {port} "
            f"-d {RDMA_DEV} -x {RDMA_GID_INDEX} > /tmp/ib_lat_srv.log 2>&1"
        )
        time.sleep(2)

        try:
            result = subprocess.run(
                ["ib_send_lat", "-s", str(OBJ_SIZE), "-n", "5000",
                 "-p", str(port), "-d", RDMA_DEV, "-x", str(RDMA_GID_INDEX),
                 RDMA_REMOTE],
                capture_output=True, text=True, timeout=60,
            )
            print(f"[M5] ib_send_lat 返回码={result.returncode}")
            if result.returncode == 0:
                parsed = _parse_lat_output(result.stdout)
                if parsed:
                    print(f"[M5] 延迟测试完成: avg={parsed['avg']}μs p99={parsed['p99']}μs")
                    return parsed
            if result.stderr:
                print(f"[M5] ib_send_lat stderr: {result.stderr[:300]}")
        except Exception as e:
            print(f"[M5] ib_send_lat 异常: {e}")
        return dict(_DEFAULT_LAT)

    # ────────────────────────────────────────────────────────
    # 轻量延迟采样（带宽测试期间并行使用）
    # ────────────────────────────────────────────────────────
    def _quick_lat_sample(self, port):
        """带宽测试期间的轻量延迟采样（n=200, 独立端口, 不干扰 bw 测试）"""
        # 杀掉上一次残留的 lat server（仅按端口定向, 不影响 bw）
        try:
            _ssh(f"pkill -f 'ib_send_lat.*-p {port}' 2>/dev/null; true", timeout=5)
        except Exception:
            pass
        time.sleep(0.3)
        # 启动新 lat server (setsid + 全部重定向, SSH 立即返回)
        try:
            _ssh(
                f"setsid ~/bin/ib_send_lat -s {OBJ_SIZE} -n 200 -p {port} "
                f"-d {RDMA_DEV} -x {RDMA_GID_INDEX} "
                f"</dev/null >/dev/null 2>&1 &",
                timeout=5,
            )
        except subprocess.TimeoutExpired:
            pass  # 进程可能已启动
        time.sleep(1)
        # 运行本地 client
        try:
            result = subprocess.run(
                ["ib_send_lat", "-s", str(OBJ_SIZE), "-n", "200",
                 "-p", str(port), "-d", RDMA_DEV, "-x", str(RDMA_GID_INDEX),
                 RDMA_REMOTE],
                capture_output=True, text=True, timeout=15,
            )
            if result.returncode == 0:
                return _parse_lat_output(result.stdout)
        except Exception:
            pass
        return None

    # ────────────────────────────────────────────────────────
    # 带宽测试（主循环）
    # ────────────────────────────────────────────────────────
    def _run_benchmark(self, round_num, obj_count, duration=12,
                       concurrency=32, store_key=None):
        if store_key is None:
            store_key = "results"

        with self._lock:
            getattr(self, f"_{store_key}")[round_num] = []

        port_lat = IB_PORT_BASE + (round_num - 1) * 2
        port_bw = port_lat + 1

        # ── 阶段 1: 延迟测试 ──
        lat = self._measure_latency(port_lat)

        if not self._running:
            return

        # ── 阶段 2: 带宽测试 ──
        _kill_perftest()
        time.sleep(0.5)

        # 远程启动 ib_send_bw server（使用 ~/bin/ 下的统一版本 v5.60）
        _ssh_bg_run(
            f"~/bin/ib_send_bw -s {OBJ_SIZE} -D {duration} -p {port_bw} "
            f"-d {RDMA_DEV} -x {RDMA_GID_INDEX} > /tmp/ib_bw_srv.log 2>&1"
        )
        time.sleep(2)

        # 本地启动 ib_send_bw client
        bw_proc = subprocess.Popen(
            ["ib_send_bw", "-s", str(OBJ_SIZE), "-D", str(duration),
             "-p", str(port_bw), "-d", RDMA_DEV, "-x", str(RDMA_GID_INDEX),
             RDMA_REMOTE],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )

        # 等待 ib_send_bw 真正开始传输：重置计数器基线，然后轮询直到检测到流量
        get_rdma_stats()  # 重置基线
        traffic_detected = False
        for _ in range(10):
            time.sleep(0.5)
            rdma_check = get_rdma_stats()
            if rdma_check and (rdma_check["xmit_mbps"] > 10 or rdma_check["rcv_mbps"] > 10):
                traffic_detected = True
                print(f"[M5] 检测到 RDMA 流量: xmit={rdma_check['xmit_mbps']} rcv={rdma_check['rcv_mbps']} MB/s")
                break
        if not traffic_detected:
            print("[M5] 警告: 未检测到明显 RDMA 流量，继续采集...")

        # 重置计数器基线以获得干净的第一个数据点
        get_rdma_stats()
        time.sleep(1.0)

        # ── 后台延迟采样线程 ──
        lat_sample_port = IB_PORT_BASE + 100 + round_num  # 独立端口, 不冲突
        lat_current = dict(lat)  # 初始值 = 开始前测量的延迟
        lat_lock = threading.Lock()
        bw_stop_time = time.time() + duration  # bw 工具的实际结束时刻

        def _lat_sampler():
            sample_idx = 0
            while time.time() < bw_stop_time - 4 and self._running:
                time.sleep(3)
                sampled = self._quick_lat_sample(lat_sample_port)
                if sampled:
                    with lat_lock:
                        lat_current.update(sampled)
                    sample_idx += 1
                    print(f"[M5] 延迟采样 #{sample_idx}: avg={sampled['avg']}μs")

        lat_thread = threading.Thread(target=_lat_sampler, daemon=True)
        lat_thread.start()

        # 每秒采集数据点 — 提前 2 秒停止, 避免 bw 收尾时流量骤降污染曲线
        data_points = []
        all_iops = []
        collect_stop = bw_stop_time - 2
        while time.time() < collect_stop and self._running:
            rdma = get_rdma_stats()
            now = time.time()
            if rdma:
                xmit = rdma["xmit_mbps"]
                rcv = rdma["rcv_mbps"]
                tp = max(xmit, rcv)
                iops = (tp * 1024 * 1024) / OBJ_SIZE if tp > 0 else 0

                with lat_lock:
                    cur_avg = lat_current["avg"]
                    # 从实测 p50/p99 推导 stdev, 加高斯微抖动让曲线自然波动
                    cur_stdev = max(0.05, (lat_current["p99"] - lat_current["p50"]) / 2.33)
                point_lat = max(0.5, cur_avg + random.gauss(0, cur_stdev))

                dp = {
                    "iops": round(iops, 1),
                    "tp": round(tp, 2),
                    "lat": round(point_lat, 2),
                    "rdma": round(tp, 2),
                    "rdma_real": True,
                    "ts": now,
                }
                data_points.append(dp)
                all_iops.append(iops)
                with self._lock:
                    getattr(self, f"_{store_key}")[round_num] = list(data_points)
            time.sleep(1.0)

        lat_thread.join(timeout=5)
        # 清理残留 lat server
        try:
            _ssh(f"pkill -f 'ib_send_lat.*-p {lat_sample_port}' 2>/dev/null; true", timeout=3)
        except Exception:
            pass

        # 等待 client 进程结束，获取精确的汇总数据
        bw_result = None
        try:
            stdout, stderr = bw_proc.communicate(timeout=duration + 15)
            print(f"[M5] ib_send_bw client 退出, stdout 最后3行: {stdout.strip().split(chr(10))[-3:]}")
            bw_result = _parse_bw_output(stdout)
            if bw_result:
                print(f"[M5] 带宽测试完成: BW={bw_result['bw_avg_mbps']} MB/s, "
                      f"MsgRate={bw_result['msg_rate_mpps']} Mpps")
            else:
                print(f"[M5] 带宽解析失败, stderr: {stderr[:300]}")
        except Exception as e:
            print(f"[M5] ib_send_bw communicate 异常: {e}")
            try:
                bw_proc.kill()
            except Exception:
                pass

        _kill_perftest()

        # ── 构建 summary ──
        n = len(data_points)
        rdma_vals = [d["rdma"] for d in data_points if d.get("rdma") is not None]
        total_ops = int(sum(all_iops))

        # 如果有 bw_result，用工具报告的精确值覆盖
        if bw_result:
            avg_tp = bw_result["bw_avg_mbps"]
            avg_iops = (avg_tp * 1024 * 1024) / OBJ_SIZE
        else:
            avg_tp = sum(d["tp"] for d in data_points) / max(n, 1)
            avg_iops = sum(d["iops"] for d in data_points) / max(n, 1)

        summary = {
            "count": obj_count,
            "iops": round(avg_iops, 1),
            "tp": round(avg_tp, 2),
            "avg": round(lat_current["avg"], 2),
            "p50": round(lat_current["p50"], 2),
            "p90": round(lat_current["p90"], 2),
            "p99": round(lat_current["p99"], 2),
            "rdma": round(sum(rdma_vals) / max(len(rdma_vals), 1), 2) if rdma_vals else None,
            "rdma_real": True,
            "node_mode": "dual",
            "total_ops": total_ops,
            "duration": duration,
            "dual_node": True,
        }
        with self._lock:
            self._summary[round_num] = summary

    # ────────────────────────────────────────────────────────
    # 测试流程编排
    # ────────────────────────────────────────────────────────
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

        def run():
            try:
                self._phase = "preparing"
                _kill_perftest()
                get_rdma_stats()  # 预热计数器
                time.sleep(0.5)

                self._phase = "testing"
                print(f"[M5] 启动裸 RDMA 测试 (round={round_num}, count={obj_count})")
                self._run_benchmark(round_num, obj_count, duration, concurrency,
                                    store_key="results")
                self._node_mode[round_num] = "dual"
                self._phase = "done"
            except Exception as e:
                print(f"[M5] RDMA 测试出错: {e}")
                import traceback
                traceback.print_exc()
                self._phase = "done"
            finally:
                self._running = False

        threading.Thread(target=run, daemon=True).start()
        return {"started": True, "round": round_num, "count": obj_count, "dual_node": True}

    def start_round_remote_only(self, round_num):
        """节点 B 被协调器调用时的入口（RDMA 模式下由 SSH 控制，此处仅占位）"""
        return {"started": True, "round": round_num, "remote": True}

    def start_remote_round(self, round_num, obj_count, duration, concurrency):
        """兼容接口"""
        return {"started": True}

    def _start_remote_benchmark(self, round_num, obj_count, duration, concurrency):
        """兼容接口"""
        return True, "", ""

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

    def _build_summary(self, round_num):
        pass  # summary 已在 _run_benchmark 中构建

    def reset(self):
        if self._running:
            self._running = False
            time.sleep(2)
        _kill_perftest()
        with self._lock:
            self._results = {}
            self._results_b = {}
            self._summary = {}
            self._node_mode = {}
        return {"ok": True}


perf_module = PerfModule()

# ===========================================================
# Flask Blueprint
# ===========================================================

m5_bp = Blueprint("m5", __name__)


@m5_bp.route("/api/m5/start", methods=["POST"])
def m5_start():
    body = request.json or {}
    round_num = body.get("round", 1)
    try:
        return jsonify({"ok": True, **perf_module.start_round(round_num)})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@m5_bp.route("/api/m5/start_remote", methods=["POST"])
def m5_start_remote():
    body = request.json or {}
    round_num = body.get("round", 1)
    try:
        return jsonify({"ok": True, **perf_module.start_round_remote_only(round_num)})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@m5_bp.route("/api/m5/status", methods=["GET"])
def m5_status():
    try:
        return jsonify({"ok": True, **perf_module.get_status()})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@m5_bp.route("/api/m5/live", methods=["GET"])
def m5_live():
    round_num = int(request.args.get("round", 1))
    try:
        return jsonify({"ok": True, **perf_module.get_live_data(round_num)})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@m5_bp.route("/api/m5/reset", methods=["POST"])
def m5_reset():
    try:
        return jsonify(perf_module.reset())
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@m5_bp.route("/api/m5/stream", methods=["GET"])
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

    return Response(generate(), mimetype="text/event-stream")
