"""
native_rdma control plane (Flask).
Non hot-path: cluster control, demo orchestration, metrics aggregation.
Hot-path is handled by the C++ data plane via UDS.
"""
from __future__ import annotations
import os
import re
import struct
import mmap
import json
import shutil
import subprocess
import time
import socket
import threading
import urllib.request
import urllib.error
import uuid
from pathlib import Path
from typing import Any, Dict
from flask import Flask, jsonify, request, send_from_directory, Response, stream_with_context
from flask_cors import CORS

from demo_orchestrator import (
    SharedObjectView,
    PerfRoundRunner,
    TierDemoScript,
)

# --------- placeholders, override via env ---------
UDS_PATH    = os.environ.get("NR_UDS_PATH",    "/tmp/native_rdma-dp.sock")
METRICS_SHM = os.environ.get("NR_METRICS_SHM", "/tmp/native_rdma-metrics.shm")
ROLE        = os.environ.get("NR_ROLE",        "A")
CTRL_PORT   = int(os.environ.get("NR_CTRL_PORT", "5000"))
# DASH_DIR 指向 *六模块* 仪表盘（M1~M6）的根目录。
# 仓库布局：<repo>/dashboard/ 是新面板，<repo>/native_rdma/dashboard/ 是旧单页面板。
# 默认相对路径 ../../dashboard 解析到仓库根下的 dashboard/。
# 如果你的部署布局不同，请用 NR_DASH_DIR 环境变量显式覆盖。
DASH_DIR    = os.environ.get(
    "NR_DASH_DIR",
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "dashboard")))
REPO_ROOT   = Path(__file__).resolve().parents[2]
FUNCTIONS_DIR = Path(os.environ.get("NR_FUNCTIONS_DIR", str(REPO_ROOT / "functions"))).resolve()
FUNCTION_DASHBOARD_COPY_DOC = Path(os.environ.get(
    "NR_FUNCTION_DASHBOARD_COPY_DOC",
    str(REPO_ROOT / "docs" / "function_dashboard验证与实现文案.md"))).resolve()
FUNCTION_DASH_DIR = os.environ.get(
    "NR_FUNCTION_DASH_DIR",
    str((REPO_ROOT / "function_dashboard").resolve()))
PERFORMANCES_DIR = Path(os.environ.get("NR_PERFORMANCES_DIR", str(REPO_ROOT / "performances"))).resolve()
PERFORMANCE_DASHBOARD_COPY_DOC = Path(os.environ.get(
    "NR_PERFORMANCE_DASHBOARD_COPY_DOC",
    str(REPO_ROOT / "docs" / "performance_dashboard验证与实现文案.md"))).resolve()
PERFORMANCE_DASH_DIR = os.environ.get(
    "NR_PERFORMANCE_DASH_DIR",
    str((REPO_ROOT / "performance_dashboard").resolve()))

app = Flask(__name__, static_folder=None)
CORS(app)

# ---------- UDS client (length-prefixed frames) ----------
# Tracks whether the C++ data plane is currently reachable on UDS.
# Flipped to False on connect/recv error, back to True on successful call.
_dp_online = {"ok": False, "last_err": ""}
_dp_lock = threading.Lock()

def _set_dp_status(ok: bool, err: str = ""):
    with _dp_lock:
        _dp_online["ok"] = ok
        _dp_online["last_err"] = err

def is_dp_online() -> bool:
    with _dp_lock:
        return _dp_online["ok"]

def uds_call(kind: str, body: bytes = b"") -> bytes:
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(2.0)
        s.connect(UDS_PATH)
        k = kind.encode()
        s.sendall(struct.pack("<I", len(k)) + k +
                  struct.pack("<I", len(body)) + body)
        rl = struct.unpack("<I", s.recv(4))[0]
        data = b""
        while len(data) < rl:
            chunk = s.recv(rl - len(data))
            if not chunk: break
            data += chunk
        s.close()
        _set_dp_status(True)
        return data
    except FileNotFoundError as e:
        _set_dp_status(False, str(e))
        return (b'{"ok":false,"err":"data plane offline (uds socket not found)",'
                b'"dp_offline":true}')
    except (ConnectionRefusedError, ConnectionResetError, BrokenPipeError,
            socket.timeout) as e:
        _set_dp_status(False, str(e))
        return (b'{"ok":false,"err":"data plane offline (' +
                str(e).encode() + b')","dp_offline":true}')
    except Exception as e:
        # Keep DP status unchanged for unknown errors, just surface them.
        return ("{\"ok\":false,\"err\":\"%s\"}" % str(e).replace('"','\\"')).encode()

# ---------- Metrics reader (mmap shared memory) ----------
# Layout matches data_plane/api/metrics_agent.h (must keep in sync).
_METRICS_FMT = "<Q Q Q Q d d d d d Q Q Q d"   # 13 fields
_METRICS_KEYS = [
    "ts_ns", "ops_total", "ops_hi", "ops_lo",
    "bw_tx_gbps", "bw_rx_gbps", "rdma_util_pct",
    "lat_avg_us", "lat_p99_us",
    "obj_dram", "obj_nvme", "obj_hdd",
    "replica_lag_us",
]
_METRICS_SIZE = struct.calcsize(_METRICS_FMT)

_rate_state = {"last_ts_ns": 0, "last_ops": 0, "ops_per_sec": 0.0}
_rate_lock  = threading.Lock()

def read_metrics():
    if not os.path.exists(METRICS_SHM):
        return {k: 0 for k in _METRICS_KEYS}
    with open(METRICS_SHM, "rb") as f:
        mm = mmap.mmap(f.fileno(), _METRICS_SIZE, prot=mmap.PROT_READ)
        raw = mm.read(_METRICS_SIZE)
        mm.close()
    if len(raw) != _METRICS_SIZE:
        return {k: 0 for k in _METRICS_KEYS}
    vals = struct.unpack(_METRICS_FMT, raw)
    m = dict(zip(_METRICS_KEYS, vals))
    # Derive instant ops/s from delta of cumulative counter.
    with _rate_lock:
        ts_ns = int(m.get("ts_ns", 0))
        ops   = int(m.get("ops_total", 0))
        last_ts = _rate_state["last_ts_ns"]
        last_op = _rate_state["last_ops"]
        if last_ts > 0 and ts_ns > last_ts:
            dt = (ts_ns - last_ts) / 1e9
            d_ops = max(0, ops - last_op)
            if dt > 0:
                _rate_state["ops_per_sec"] = d_ops / dt
        _rate_state["last_ts_ns"] = ts_ns
        _rate_state["last_ops"]   = ops
        m["ops_per_sec"] = _rate_state["ops_per_sec"]
    return m

# ---------- REST API ----------
@app.route("/api/cluster/status")
def cluster_status():
    resp = uds_call("RPC_CLUSTER_STATUS").decode(errors="replace")
    try: body = json.loads(resp)
    except Exception: body = {"raw": resp}
    body["self"] = ROLE
    dp_up = is_dp_online()
    body["dp_online"] = dp_up
    metrics = read_metrics()
    if not dp_up:
        # DP offline -> shm snapshot is stale; freeze derived rate and
        # surface a stale flag so the UI can render "offline" state
        # instead of displaying a frozen cumulative counter as if it were live.
        metrics = dict(metrics)
        metrics["ops_per_sec"] = 0.0
        metrics["stale"] = True
    body["metrics"] = metrics
    # ---- Top-level aliases so the dashboard can read them directly ----
    # The C++ UDS returns `peer_alive`; UI expects `rdma_connected`.
    # When DP is offline, force rdma_connected=False regardless of what
    # the (now unreachable) UDS body would have said.
    body["rdma_connected"] = bool(dp_up and body.get("peer_alive", False))
    # replica_lag_us comes from the metrics shm, surface it at the top too.
    body["replica_lag_us"] = metrics.get("replica_lag_us", 0.0)
    return jsonify(body)

@app.route("/api/kv/put", methods=["POST"])
def kv_put():
    j = request.get_json(force=True)
    key = j.get("key", "")
    val = j.get("val", "")
    # TODO: serialize to protobuf KvPutReq; for now pass raw key=val text.
    payload = f"{key}\x00{val}".encode()
    resp = uds_call("RPC_KV_PUT", payload)
    return resp, 200, {"Content-Type": "application/json"}

@app.route("/api/kv/get")
def kv_get():
    key = request.args.get("key", "")
    resp = uds_call("RPC_KV_GET", key.encode())
    return resp, 200, {"Content-Type": "application/json"}

@app.route("/api/metrics")
def metrics():
    return jsonify(read_metrics())

@app.route("/api/snapshot", methods=["POST"])
def snapshot():
    j = request.get_json(force=True)
    tag = j.get("tag", time.strftime("%Y%m%d_%H%M%S"))
    resp = uds_call("RPC_SNAPSHOT", tag.encode())
    return resp, 200, {"Content-Type": "application/json"}

@app.route("/api/tier/stats")
def tier_stats():
    resp = uds_call("RPC_TIER_STATS")
    return resp, 200, {"Content-Type": "application/json"}

@app.route("/api/tier/demote", methods=["POST"])
def tier_demote():
    j = request.get_json(force=True)
    key  = j.get("key", "")
    tier = j.get("tier", "nvme")   # "nvme" | "hdd"
    payload = f"{key}\x00{tier}".encode()
    resp = uds_call("RPC_TIER_DEMOTE", payload)
    return resp, 200, {"Content-Type": "application/json"}

@app.route("/api/prefetch/stats")
def prefetch_stats():
    key = request.args.get("key", "")
    resp = uds_call("RPC_PREFETCH_STATS", key.encode())
    return resp, 200, {"Content-Type": "application/json"}

@app.route("/api/compress/stats")
def compress_stats():
    resp = uds_call("RPC_COMPRESS_STATS")
    return resp, 200, {"Content-Type": "application/json"}

@app.route("/api/admin/flush", methods=["POST"])
def admin_flush():
    # Wipe the KV index, free DRAM slab slots and reset all counters.
    # Use ONLY for recovering from bench residue during demos.
    resp = uds_call("RPC_ADMIN_FLUSH")
    return resp, 200, {"Content-Type": "application/json"}

# ============================================================
# 演示用 REST (重写版, 对应 docs/演示要求.md 三条演示项)
#
#   §3 跨节点对象读写/同步   -> /api/demo3/*
#   §5 吞吐量 & 扩展性        -> /api/demo5/*
#   §6 分级存储能力           -> /api/demo6/*
#
# 同时提供 /api/peer/* 反向代理到 PEER_URL（A->B 或 B->A），
# 这样前端**始终只打本端 Flask**，完全绕开浏览器跨源/CORS 问题。
# ============================================================

_DASH_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_obj_view  = SharedObjectView()
_perf_run  = PerfRoundRunner(_DASH_ROOT, ROLE, uds_call)
_tier_demo = TierDemoScript(uds_call, _DASH_ROOT, ROLE)

# peer url: 由 env 注入，例如 "http://192.168.0.214:5001"
PEER_URL = os.environ.get("NR_PEER_URL", "")


def _peer_get(path: str) -> tuple:
    """Fetch <PEER_URL><path> and return (body_bytes, status, content_type)."""
    if not PEER_URL:
        return (b'{"ok":false,"error":"NR_PEER_URL not set"}',
                503, "application/json")
    url = PEER_URL.rstrip("/") + path
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=3) as r:
            return (r.read(), r.status,
                    r.headers.get("Content-Type", "application/json"))
    except urllib.error.HTTPError as e:
        return (e.read() or f'{{"ok":false,"error":"peer {e.code}"}}'.encode(),
                e.code, "application/json")
    except Exception as e:
        return (f'{{"ok":false,"error":"peer unreachable: {e}"}}'.encode(),
                502, "application/json")


def _peer_post(path: str, body_json: Any) -> tuple:
    if not PEER_URL:
        return (b'{"ok":false,"error":"NR_PEER_URL not set"}',
                503, "application/json")
    url = PEER_URL.rstrip("/") + path
    data = json.dumps(body_json or {}).encode()
    try:
        req = urllib.request.Request(
            url, data=data, method="POST",
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as r:
            return (r.read(), r.status,
                    r.headers.get("Content-Type", "application/json"))
    except urllib.error.HTTPError as e:
        return (e.read() or f'{{"ok":false,"error":"peer {e.code}"}}'.encode(),
                e.code, "application/json")
    except Exception as e:
        return (f'{{"ok":false,"error":"peer unreachable: {e}"}}'.encode(),
                502, "application/json")


# ---------- Generic peer reverse proxy ----------
@app.route("/api/peer/<path:rest>", methods=["GET", "POST"])
def peer_proxy(rest):
    """Forward the request to PEER_URL with the same sub-path.
    Keeps the browser origin single, so no CORS preflight, no mixed-content.

    GET  /api/peer/demo3/cluster  -> GET  $PEER_URL/api/demo3/cluster
    POST /api/peer/demo3/write    -> POST $PEER_URL/api/demo3/write (body forwarded)
    """
    # 保留查询串
    qs = request.query_string.decode() if request.query_string else ""
    target = "/api/" + rest + (("?" + qs) if qs else "")
    if request.method == "GET":
        body, status, ct = _peer_get(target)
    else:
        body, status, ct = _peer_post(target, request.get_json(silent=True) or {})
    return body, status, {"Content-Type": ct}


# ============================================================
# §3  跨节点对象读写 / 同步
# ============================================================
def _cluster_core() -> Dict[str, Any]:
    raw = uds_call("RPC_CLUSTER_STATUS").decode(errors="replace")
    try:    cs = json.loads(raw)
    except Exception: cs = {"raw": raw}
    m = read_metrics()
    return {
        "ok":              True,
        "role":            ROLE,
        "self_ip":         cs.get("self", "?"),
        "peer_alive":      bool(cs.get("peer_alive", False)),
        "peer_num_qp":     int(cs.get("peer_num_qp", 0) or 0),
        "rdma_connected":  bool(is_dp_online() and cs.get("peer_alive", False)),
        "dp_online":       is_dp_online(),
        "degraded_puts":   int(cs.get("degraded_puts", 0) or 0),
        "degraded_bytes":  int(cs.get("degraded_bytes", 0) or 0),
        "metrics":         m,
        "replica_lag_us":  float(m.get("replica_lag_us", 0.0) or 0.0),
        "objects_here":    len(_obj_view.list_all()),
    }


def _notify_peer_async(kind: str, name: str, data: str = ""):
    """Tell the peer Flask that we just wrote/modified/deleted <name>,
    so its SharedObjectView stays in sync. Fire-and-forget; the peer's
    DP already has the actual bytes via RDMA replication, this is pure
    metadata so both UIs can show the object."""
    if not PEER_URL:
        return
    payload = {"op": kind, "name": name, "data": data, "from": ROLE}
    def _fire():
        try:
            _peer_post("/api/demo3/announce", payload)
        except Exception:
            pass
    threading.Thread(target=_fire, daemon=True).start()


@app.route("/api/demo3/cluster")
def demo3_cluster():
    return jsonify(_cluster_core())


@app.route("/api/demo3/objects")
def demo3_objects():
    return jsonify({"ok": True,
                    "role":    ROLE,
                    "count":   len(_obj_view.list_all()),
                    "objects": _obj_view.list_all()})


def _lat_us(t0_ns: int) -> int:
    return max(0, int((time.time_ns() - t0_ns) / 1000))


@app.route("/api/demo3/write", methods=["POST"])
def demo3_write():
    j    = request.get_json(force=True) or {}
    name = (j.get("name") or "").strip()
    data = j.get("data") or ""
    if not name:
        return jsonify({"ok": False, "error": "name required"}), 400
    body = name.encode() + b"\x00" + data.encode()
    t0   = time.time_ns()
    raw  = uds_call("RPC_KV_PUT", body).decode(errors="replace")
    lat  = _lat_us(t0)
    try:    r = json.loads(raw)
    except Exception: r = {"ok": False, "err": raw[:200]}
    if not r.get("ok"):
        return jsonify({"ok": False, "error": r.get("err", "put failed"),
                        "latency_us": lat}), 500
    rec = _obj_view.upsert(name, data, via="write",
                           extra={"repl_ns": r.get("repl_ns"),
                                  "degraded": bool(r.get("degraded", False)),
                                  "route": r.get("route", {})})
    _notify_peer_async("write", name, data)
    return jsonify({
        "ok":          True,
        "op":          "write",
        "name":        name,
        "size":        rec["size"],
        "hash":        rec["hash"],
        "version":     rec["version"],
        "latency_us":  lat,
        "repl_ns":     r.get("repl_ns", 0),
        "degraded":    rec.get("degraded", False),
        "route":       r.get("route", {}),
        "node":        ROLE,
        "ts":          rec["ts"],
    })


@app.route("/api/demo3/modify", methods=["POST"])
def demo3_modify():
    # 等同 write；单独路由是为了让事件日志里区分操作类型
    j    = request.get_json(force=True) or {}
    name = (j.get("name") or "").strip()
    data = j.get("data") or ""
    if not name:
        return jsonify({"ok": False, "error": "name required"}), 400
    body = name.encode() + b"\x00" + data.encode()
    t0   = time.time_ns()
    raw  = uds_call("RPC_KV_PUT", body).decode(errors="replace")
    lat  = _lat_us(t0)
    try:    r = json.loads(raw)
    except Exception: r = {"ok": False, "err": raw[:200]}
    if not r.get("ok"):
        return jsonify({"ok": False, "error": r.get("err", "modify failed"),
                        "latency_us": lat}), 500
    rec = _obj_view.upsert(name, data, via="modify",
                           extra={"repl_ns": r.get("repl_ns")})
    _notify_peer_async("modify", name, data)
    return jsonify({
        "ok":         True,
        "op":         "modify",
        "name":       name,
        "size":       rec["size"],
        "hash":       rec["hash"],
        "version":    rec["version"],
        "latency_us": lat,
        "repl_ns":    r.get("repl_ns", 0),
        "node":       ROLE,
        "ts":         rec["ts"],
    })


@app.route("/api/demo3/read")
def demo3_read():
    name = request.args.get("name", "").strip()
    no_fallback = request.args.get("no_fallback", "") == "1"
    if not name:
        return jsonify({"ok": False, "error": "name required"}), 400
    t0  = time.time_ns()
    raw = uds_call("RPC_KV_GET", name.encode()).decode(errors="replace")
    lat = _lat_us(t0)
    try:    r = json.loads(raw)
    except Exception: r = {"ok": False, "err": raw[:200]}

    if r.get("ok"):
        hit = r.get("hit", "?")
        _obj_view.touch(name, hit, lat)
        return jsonify({
            "ok":         True,
            "op":         "read",
            "name":       name,
            "data":       r.get("val", ""),
            "hit":        hit,                    # local / remote / nvme / hdd
            "size":       r.get("size", 0),
            "latency_us": lat,
            "node":       ROLE,
            "ts":         time.strftime("%H:%M:%S"),
        })

    # 本端 DP 说 not found；这通常是因为该对象的 primary 在对端
    # —— ObjectRouter 一致性哈希把这个 key 路由到了 peer，所以 peer
    # 才是写入源头。对端 DP 的 KV index 有记录，我们 HTTP 去问一下。
    if not no_fallback and PEER_URL:
        body, status, _ct = _peer_get(
            "/api/demo3/read?name=" + name + "&no_fallback=1")
        if status == 200:
            try:    pj = json.loads(body.decode())
            except Exception: pj = {}
            if pj.get("ok"):
                # 我们本端也把对象加入视图，方便后续 UI 展示
                _obj_view.upsert(name, pj.get("data", ""), via="remote_read",
                                 extra={"synced": True,
                                        "src_node": pj.get("node")})
                pj["fallback"] = True
                pj["primary_node"] = pj.get("node", "?")
                pj["node"] = ROLE
                pj["latency_us"] = int(pj.get("latency_us", 0)) + lat
                pj["hit"] = "remote:" + str(pj.get("hit", "?"))
                return jsonify(pj)

    return jsonify({"ok": False, "error": r.get("err", "not found"),
                    "latency_us": lat, "node": ROLE}), 404


@app.route("/api/demo3/delete", methods=["POST"])
def demo3_delete():
    j    = request.get_json(force=True) or {}
    name = (j.get("name") or "").strip()
    if not name:
        return jsonify({"ok": False, "error": "name required"}), 400
    existed = _obj_view.delete(name)
    _notify_peer_async("delete", name)
    return jsonify({"ok": existed, "op": "delete", "name": name,
                    "node": ROLE, "ts": time.strftime("%H:%M:%S"),
                    "error": None if existed else "not present in local view"})


@app.route("/api/demo3/announce", methods=["POST"])
def demo3_announce():
    """Peer just wrote/modified/deleted an object; sync our view so
    the UI for this node also lists the object without waiting for a
    manual read. Metadata-only: the actual bytes already traveled
    over RDMA at PUT time."""
    j    = request.get_json(force=True) or {}
    op   = (j.get("op") or "").strip()
    name = (j.get("name") or "").strip()
    data = j.get("data") or ""
    frm  = j.get("from") or "peer"
    if not name or op not in ("write", "modify", "delete"):
        return jsonify({"ok": False, "error": "bad payload"}), 400
    if op == "delete":
        _obj_view.delete(name)
    else:
        _obj_view.upsert(name, data, via=f"sync_from_{frm}",
                         extra={"synced": True, "src_node": frm})
    return jsonify({"ok": True, "op": op, "name": name, "node": ROLE})


@app.route("/api/demo3/flush", methods=["POST"])
def demo3_flush():
    # 在 §3 演示开始前调用；同时 flush DP 和本端视图
    try: uds_call("RPC_ADMIN_FLUSH")
    except Exception: pass
    _obj_view.clear()
    return jsonify({"ok": True, "node": ROLE})


# ============================================================
# §5  吞吐量 & 扩展性
# ============================================================
@app.route("/api/demo5/start", methods=["POST"])
def demo5_start():
    j = request.get_json(force=True) or {}
    try: round_id = int(j.get("round", 0))
    except (TypeError, ValueError): round_id = 0
    r = _perf_run.start(round_id)
    return jsonify(r), (200 if r.get("ok") else 400)

@app.route("/api/demo5/perf01/start", methods=["POST"])
def demo5_perf01_start():
    r = _perf_run.start_perf01()
    return jsonify(r), (200 if r.get("ok") else 400)

@app.route("/api/demo5/live")
def demo5_live():
    try: rid = int(request.args.get("round", "1"))
    except ValueError: rid = 1
    return jsonify(_perf_run.live(rid))

@app.route("/api/demo5/snapshot")
def demo5_snapshot():
    # 一次性拉回所有轮次 + 本端当前 shm 即时指标（用于页首"实时指标"区）
    s = _perf_run.snapshot_all()
    s["metrics"] = read_metrics()
    s["node"]    = ROLE
    return jsonify(s)

@app.route("/api/demo5/reset", methods=["POST"])
def demo5_reset():
    _perf_run.reset()
    return jsonify({"ok": True, "node": ROLE})


# ============================================================
# §6  分级存储能力
# ============================================================
@app.route("/api/demo6/start", methods=["POST"])
def demo6_start():
    r = _tier_demo.start()
    return jsonify(r), (200 if r.get("ok") else 400)

@app.route("/api/demo6/next_step", methods=["POST"])
def demo6_next_step():
    """步进模式：阻塞式执行下一步，返回 {ok, step_done, next_step, next_label}。
    前端点击"下一步"按钮时调用。如果该步本身耗时较长（例如 step2 批量写入、
    step5 阶段 A 3 秒等待），HTTP 连接会阻塞直到步骤完成再返回。
    """
    r = _tier_demo.next_step()
    return jsonify(r), (200 if r.get("ok") else 400)

@app.route("/api/demo6/status")
def demo6_status():
    return jsonify(_tier_demo.status())

@app.route("/api/demo6/stream")
def demo6_stream():
    @stream_with_context
    def gen():
        for chunk in _tier_demo.stream():
            yield chunk
    return Response(gen(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache",
                             "X-Accel-Buffering": "no"})

@app.route("/api/demo6/reset", methods=["POST"])
def demo6_reset():
    _tier_demo.reset()
    return jsonify({"ok": True, "node": ROLE})

@app.route("/api/demo6/snapshot/<name>")
def demo6_snapshot(name):
    return jsonify(_tier_demo.snapshot_detail(name))

# ============================================================
# Demo APIs (W6): thin HTTP wrappers over the new data-plane RPCs
# that the dashboard pages m7..m10 call from the browser.
# Each group mirrors one functional requirement from docs/功能要求.md.
# ============================================================

# ---- m7: routing / consistent hash ----
@app.route("/api/route/query")
def route_query():
    # GET /api/route/query?key=<...>
    # Returns: {ok, key, primary, replica, local_is_primary, self}
    key = request.args.get("key", "")
    resp = uds_call("RPC_ROUTE_QUERY", key.encode())
    return resp, 200, {"Content-Type": "application/json"}

@app.route("/api/route/scan")
def route_scan():
    # GET /api/route/scan?prefix=demo_&count=20
    # Convenience: fan-out RPC_ROUTE_QUERY over a batch of keys so the
    # UI can render a sharding heat-map in a single request.
    prefix = request.args.get("prefix", "demo_")
    try: count = max(1, min(200, int(request.args.get("count", "20"))))
    except ValueError: count = 20
    results = []
    for i in range(count):
        k = f"{prefix}{i}"
        raw = uds_call("RPC_ROUTE_QUERY", k.encode())
        try: results.append(json.loads(raw.decode()))
        except Exception: results.append({"ok": False, "key": k, "raw": raw.decode(errors="replace")})
    return jsonify({"ok": True, "self": ROLE, "count": count, "items": results})

# ---- m8: tenant isolation ACL ----
@app.route("/api/iso/list")
def iso_list():
    resp = uds_call("RPC_ISO_LIST")
    return resp, 200, {"Content-Type": "application/json"}

@app.route("/api/iso/allow", methods=["POST"])
def iso_allow():
    j = request.get_json(force=True)
    tid  = int(j.get("tenant_id", 0))
    pool = j.get("pool", "default/slab1k")
    resp = uds_call("RPC_ISO_ALLOW", f"{tid} {pool}".encode())
    return resp, 200, {"Content-Type": "application/json"}

@app.route("/api/iso/deny", methods=["POST"])
def iso_deny():
    j = request.get_json(force=True)
    tid  = int(j.get("tenant_id", 0))
    pool = j.get("pool", "default/slab1k")
    resp = uds_call("RPC_ISO_DENY", f"{tid} {pool}".encode())
    return resp, 200, {"Content-Type": "application/json"}

@app.route("/api/iso/kv_put", methods=["POST"])
def iso_kv_put():
    # Convenience: do a KV_PUT *with* a tenant prefix, so the demo UI
    # can show "T7:key -> ALLOW / T7:key -> DENY" without having to
    # build the wire body on the frontend.
    j = request.get_json(force=True)
    tid = int(j.get("tenant_id", 0))
    key = j.get("key", "")
    val = j.get("val", "")
    body = f"T{tid}:{key}\x00{val}".encode()
    resp = uds_call("RPC_KV_PUT", body)
    return resp, 200, {"Content-Type": "application/json"}

@app.route("/api/iso/kv_get")
def iso_kv_get():
    tid = int(request.args.get("tenant_id", "0"))
    key = request.args.get("key", "")
    resp = uds_call("RPC_KV_GET", f"T{tid}:{key}".encode())
    return resp, 200, {"Content-Type": "application/json"}

# ---- m9: high availability / degraded mode ----
# Peer control is strictly optional and disabled unless the operator
# opts in explicitly via env vars -- we never bake IPs into the code.
#   NR_PEER_SSH       (e.g. "user@peer.example.com")
#   NR_PEER_DP_PATH   (absolute path to native_rdma_dp on the peer)
#   NR_PEER_START_CMD (optional: full command used to start the peer DP)
PEER_SSH       = os.environ.get("NR_PEER_SSH", "")
PEER_DP_PATH   = os.environ.get("NR_PEER_DP_PATH", "")
PEER_START_CMD = os.environ.get("NR_PEER_START_CMD", "")

def _peer_ctl_ok() -> bool:
    return bool(PEER_SSH) and bool(PEER_DP_PATH)

@app.route("/api/ha/status")
def ha_status():
    # Mirror of /api/cluster/status but trimmed down to just the bits
    # the HA demo page cares about: peer heartbeat, degraded counters.
    raw = uds_call("RPC_CLUSTER_STATUS").decode(errors="replace")
    try: body = json.loads(raw)
    except Exception: body = {"ok": False, "raw": raw}
    body["self"]       = ROLE
    body["dp_online"]  = is_dp_online()
    body["peer_ctl"]   = _peer_ctl_ok()
    return jsonify(body)

def _ssh_run(cmd: str, timeout: float = 5.0) -> dict:
    import subprocess
    try:
        out = subprocess.run(
            ["ssh", "-o", "BatchMode=yes",
             "-o", "ConnectTimeout=3",
             "-o", "StrictHostKeyChecking=no",
             PEER_SSH, cmd],
            capture_output=True, text=True, timeout=timeout)
        return {"ok": (out.returncode == 0), "rc": out.returncode,
                "stdout": out.stdout, "stderr": out.stderr}
    except Exception as e:
        return {"ok": False, "err": str(e)}

@app.route("/api/ha/kill_peer", methods=["POST"])
def ha_kill_peer():
    # Intentionally SIGKILL the peer data plane to demonstrate
    # degraded-mode behavior. Requires NR_PEER_SSH + NR_PEER_DP_PATH.
    if not _peer_ctl_ok():
        return jsonify({"ok": False,
                        "err": "peer control disabled: set NR_PEER_SSH and "
                               "NR_PEER_DP_PATH before starting app.py"}), 400
    # Match by full path so we don't accidentally kill our own ssh session.
    r = _ssh_run(f"pkill -9 -f '{PEER_DP_PATH}'")
    return jsonify({"ok": True, "action": "kill_peer", "ssh": r})

@app.route("/api/ha/restore_peer", methods=["POST"])
def ha_restore_peer():
    # Best-effort restart via NR_PEER_START_CMD (a full shell command
    # the operator chose at deploy time). If it's not set we just
    # surface guidance rather than guessing arguments.
    if not _peer_ctl_ok():
        return jsonify({"ok": False,
                        "err": "peer control disabled"}), 400
    if not PEER_START_CMD:
        return jsonify({"ok": False,
                        "err": "NR_PEER_START_CMD not set; restore the peer "
                               "manually with your start_node.sh equivalent"}), 400
    r = _ssh_run(PEER_START_CMD, timeout=8.0)
    return jsonify({"ok": True, "action": "restore_peer", "ssh": r})

# ---- m10: in-run simulation capture ----
@app.route("/api/sim/run", methods=["POST"])
def sim_run():
    # Body (JSON): entities, events, threads, step_us, stress, capture_every_n
    j = request.get_json(force=True) or {}
    parts = []
    for k in ("entities", "events", "threads", "step_us", "stress",
              "capture_every_n"):
        if k in j: parts.append(f"{k}={int(j[k])}")
    resp = uds_call("RPC_SIM_RUN", "&".join(parts).encode())
    return resp, 200, {"Content-Type": "application/json"}

@app.route("/api/sim/capture/stats")
def sim_cap_stats():
    resp = uds_call("RPC_SIM_CAPTURE_STATS")
    return resp, 200, {"Content-Type": "application/json"}

@app.route("/api/sim/capture/reset", methods=["POST"])
def sim_cap_reset():
    resp = uds_call("RPC_SIM_CAPTURE_RESET")
    return resp, 200, {"Content-Type": "application/json"}

@app.route("/api/sim/capture/wal_head")
def sim_cap_wal_head():
    # Returns the first N events decoded from the capture WAL so the UI
    # can render a "what got captured" preview. Path is derived from
    # the C++ default (<capture_dir>/sim_<role>.log); overridable via env.
    cap_dir = os.environ.get("NR_SIM_CAPTURE_DIR", "/tmp/nr_sim_capture")
    cap_tag = os.environ.get("NR_SIM_CAPTURE_TAG", ROLE)
    path = os.path.join(cap_dir, f"sim_{cap_tag}.log")
    try: limit = max(1, min(200, int(request.args.get("limit", "20"))))
    except ValueError: limit = 20
    out = {"ok": True, "path": path, "size": 0, "events": []}
    if not os.path.exists(path):
        out["ok"] = False
        out["err"] = "wal not found"
        return jsonify(out)
    out["size"] = os.path.getsize(path)
    # struct: ts_ns(Q) entity(Q) peer(Q) type(H) blob_len(H) reserved(I) = 32 B
    HDR = struct.Struct("<QQQHHI")
    with open(path, "rb") as f:
        for _ in range(limit):
            h = f.read(HDR.size)
            if len(h) < HDR.size: break
            ts_ns, eid, peer, t, blen, _r = HDR.unpack(h)
            blob = f.read(blen)
            out["events"].append({
                "ts_ns":     ts_ns,
                "entity_id": eid,
                "peer_id":   peer,
                "type":      t,
                "type_name": {1: "ObjectAttr", 2: "InteractionEvent"}.get(t, f"type_{t}"),
                "blob_len":  blen,
                "blob_hex":  blob.hex(),
            })
    return jsonify(out)

# ---------- Function acceptance dashboard APIs ----------
_FUNCTION_MODULES = {
    "storage": {
        "display_name": "多级异构的高效能存储模块",
        "count": 6,
        "functions": [
            ("FN-1", "仿真引擎异构存储统一访问接口"),
            ("FN-2", "多层感知、冷热分离与调度"),
            ("FN-3", "多策略预取机制"),
            ("FN-4", "可配置压缩与去重"),
            ("FN-5", "IO 调度与优先级管理"),
            ("FN-6", "仿真数据运行中采集"),
        ],
    },
    "rdma": {
        "display_name": "RDMA 分布式仿真计算模块",
        "count": 5,
        "functions": [
            ("FN-1", "RDMA 与 TCP/IP 统一通信层"),
            ("FN-2", "聚合数据传输"),
            ("FN-3", "流量优先级机制"),
            ("FN-4", "CPU 与 GPU 高速直通访问"),
            ("FN-5", "分布式节点路由转发与负载均衡"),
        ],
    },
    "mempool": {
        "display_name": "一致性总线内存池化仿真计算模块",
        "count": 6,
        "functions": [
            ("FN-1", "RDMA 语义远程内存访问与零拷贝"),
            ("FN-2", "分布式内存池 API"),
            ("FN-3", "内存池统一命名机制"),
            ("FN-4", "跨节点内存自适应分配与热数据迁移"),
            ("FN-5", "任务级与用户级内存隔离"),
            ("FN-6", "内存池高可靠机制"),
        ],
    },
}
_FUNCTION_STATUS_TEXT = {
    "PASS": "通过",
    "FAIL": "失败",
    "SKIP": "跳过",
    "WAIVED": "跳过",
}
_FUNCTION_ALLOWED_ENV = {
    "CTRL_URL",
    "UDS",
    "REQUIRE_PEER",
    "ALLOW_DESTRUCTIVE",
    "CURRENT_NODE",
    "PEER_SSH",
    "PEER_DP_PATH",
    "PEER_START_CMD",
}
_FUNCTION_DEFAULT_ENV = {
    "CTRL_URL": "http://127.0.0.1:5000",
    "UDS": "/tmp/native_rdma-dp.sock",
    "REQUIRE_PEER": "1",
    "ALLOW_DESTRUCTIVE": "0",
    "CURRENT_NODE": ROLE,
}
_FUNCTION_JOBS: dict[str, dict[str, Any]] = {}
_FUNCTION_JOB_LOCK = threading.Lock()
_FUNCTION_RUN_LOCK = threading.Lock()
_DASHBOARD_COPY_CACHE: dict[str, Any] = {"mtime": -1.0, "data": {}}
_PERFORMANCE_MODULES = {
    "performance": {
        "display_name": "性能要求",
        "count": 9,
        "functions": [
            ("PF-1", "RDMA 网络环境分布式通讯能力"),
            ("PF-2", "RDMA 网络环境下对象传输能力"),
            ("PF-3", "RDMA 网络环境下 QoS 事件优先级传输能力"),
            ("PF-4", "RDMA 网络环境下对象数据聚合传输能力"),
            ("PF-5", "RDMA 网络环境下批处理能力"),
            ("PF-6", "多级存储读写能力"),
            ("PF-7", "仿真引擎定期备份存储能力"),
            ("PF-8", "RDMA 网络环境下仿真引擎运行能力"),
            ("PF-9", "仿真引擎内存池化能力"),
        ],
    },
}
_PERFORMANCE_ALLOWED_ENV = {
    "CTRL_URL",
    "UDS",
    "REQUIRE_PEER",
    "CURRENT_NODE",
    "DUR",
    "THREADS",
    "LINK_GBPS",
    "MEASURED_RUNS",
    "HI_EVENTS",
    "LO_EVENTS",
    "VAL_SIZE",
    "KEYSPACE",
    "PUT_THREADS",
    "GET_THREADS",
    "BACKUP_PATH",
    "BACKUP_TEST_PATH",
    "RAID5_CONFIRMED",
    "PF7_BACKEND",
    "BACKUP_FSYNC",
    "QUEUE_DEPTH",
    "SIM_NODES",
    "ENTITIES",
    "ENTITY_SIZE",
    "EVENTS",
    "STEP_US",
    "STRESS",
    "OBJECT_SIZE",
}
_PERFORMANCE_DEFAULT_ENV = {
    "CTRL_URL": "http://127.0.0.1:5000",
    "UDS": "/tmp/native_rdma-dp.sock",
    "REQUIRE_PEER": "1",
    "CURRENT_NODE": ROLE,
}
_PERFORMANCE_JOBS: dict[str, dict[str, Any]] = {}
_PERFORMANCE_JOB_LOCK = threading.Lock()
_PERFORMANCE_RUN_LOCK = threading.Lock()
_PERFORMANCE_COPY_CACHE: dict[str, Any] = {"mtime": -1.0, "data": {}}


def _display_name(module: str, fn_id: str) -> str:
    for item_fn_id, name in _FUNCTION_MODULES[module]["functions"]:
        if item_fn_id == fn_id:
            return name
    return fn_id


def _validate_module(module: str) -> str:
    if module not in _FUNCTION_MODULES:
        raise ValueError("未知模块")
    return module


def _validate_fn(module: str, fn_id: str) -> str:
    _validate_module(module)
    if not re.fullmatch(r"FN-[0-9]+", fn_id or ""):
        raise ValueError("未知功能点")
    allowed = {item[0] for item in _FUNCTION_MODULES[module]["functions"]}
    if fn_id not in allowed:
        raise ValueError("未知功能点")
    return fn_id


def _safe_fn_dir(module: str, fn_id: str) -> Path:
    module = _validate_module(module)
    fn_id = _validate_fn(module, fn_id)
    fn_dir = (FUNCTIONS_DIR / module / fn_id).resolve()
    base = (FUNCTIONS_DIR / module).resolve()
    if not str(fn_dir).startswith(str(base) + os.sep) or not fn_dir.is_dir():
        raise ValueError("功能点目录不可用")
    return fn_dir


def _performance_display_name(module: str, pf_id: str) -> str:
    for item_pf_id, name in _PERFORMANCE_MODULES[module]["functions"]:
        if item_pf_id == pf_id:
            return name
    return pf_id


def _validate_performance_module(module: str) -> str:
    if module not in _PERFORMANCE_MODULES:
        raise ValueError("未知性能模块")
    return module


def _validate_pf(module: str, pf_id: str) -> str:
    _validate_performance_module(module)
    if not re.fullmatch(r"PF-[0-9]+", pf_id or ""):
        raise ValueError("未知性能点")
    allowed = {item[0] for item in _PERFORMANCE_MODULES[module]["functions"]}
    if pf_id not in allowed:
        raise ValueError("未知性能点")
    return pf_id


def _safe_pf_dir(module: str, pf_id: str) -> Path:
    _validate_performance_module(module)
    pf_id = _validate_pf(module, pf_id)
    pf_dir = (PERFORMANCES_DIR / pf_id).resolve()
    base = PERFORMANCES_DIR.resolve()
    if not str(pf_dir).startswith(str(base) + os.sep) or not pf_dir.is_dir():
        raise ValueError("性能点目录不可用")
    return pf_dir


def _read_text(path: Path, limit: int = 1024 * 1024) -> str:
    if not path.exists() or not path.is_file():
        return ""
    with open(path, "rb") as f:
        data = f.read(limit + 1)
    text = data[:limit].decode("utf-8", errors="replace")
    if len(data) > limit:
        text += "\n\n[内容已截断]"
    return text


def _read_json(path: Path) -> Any:
    text = _read_text(path)
    if not text:
        return {}
    try:
        return json.loads(text)
    except Exception as exc:
        return {"_parse_error": str(exc), "_raw": text[:2000]}


def _rel_path(path: str | Path | None) -> str:
    if not path:
        return ""
    try:
        return str(Path(path).resolve().relative_to(REPO_ROOT))
    except Exception:
        return str(path)


def _dashboard_lines(markdown: str) -> list[str]:
    return str(markdown or "").replace("\r\n", "\n").split("\n")


def _dashboard_subsection(markdown: str, title: str) -> str:
    lines = _dashboard_lines(markdown)
    start = -1
    escaped = re.escape(title)
    for idx, line in enumerate(lines):
        if re.fullmatch(rf"###\s+{escaped}\s*", line.strip()):
            start = idx
            break
    if start < 0:
        return ""
    out = []
    for line in lines[start + 1:]:
        if re.match(r"^###\s+", line.strip()):
            break
        out.append(line)
    return "\n".join(out).strip()


def _dashboard_named_list(markdown: str, title: str) -> list[str]:
    lines = _dashboard_lines(markdown)
    start = -1
    escaped = re.escape(title)
    for idx, line in enumerate(lines):
        if re.fullmatch(rf"{escaped}[：:]\s*", line.strip()):
            start = idx
            break
    if start < 0:
        return []
    out: list[str] = []
    for line in lines[start + 1:]:
        stripped = line.strip()
        if not stripped:
            continue
        if re.fullmatch(r"[^-+*#`][^：:]{0,40}[：:]\s*", stripped):
            break
        item = re.match(r"^[-*+]\s+(.*)", stripped)
        if item:
            out.append(item.group(1).strip())
        elif out:
            out[-1] = f"{out[-1]} {stripped}".strip()
    return out


def _parse_dashboard_copy_doc() -> dict[tuple[str, str], dict[str, Any]]:
    try:
        mtime = FUNCTION_DASHBOARD_COPY_DOC.stat().st_mtime
    except OSError:
        _DASHBOARD_COPY_CACHE["mtime"] = -1.0
        _DASHBOARD_COPY_CACHE["data"] = {}
        return {}
    if _DASHBOARD_COPY_CACHE.get("mtime") == mtime:
        data = _DASHBOARD_COPY_CACHE.get("data")
        return data if isinstance(data, dict) else {}

    text = _read_text(FUNCTION_DASHBOARD_COPY_DOC, 2 * 1024 * 1024)
    parsed: dict[tuple[str, str], dict[str, Any]] = {}
    current_key: tuple[str, str] | None = None
    current_lines: list[str] = []

    def flush_current():
        if not current_key:
            return
        block = "\n".join(current_lines)
        goal = _dashboard_subsection(block, "验证目标")
        implementation = _dashboard_subsection(block, "实现方案")
        test_section = _dashboard_subsection(block, "测试方案")
        item = {
            "goal": goal,
            "implementation": implementation,
            "prerequisites": _dashboard_named_list(test_section, "前置条件"),
            "test_plan": _dashboard_named_list(test_section, "测试方案"),
            "source_doc": _rel_path(FUNCTION_DASHBOARD_COPY_DOC),
        }
        if goal or implementation or item["prerequisites"] or item["test_plan"]:
            parsed[current_key] = item

    for line in _dashboard_lines(text):
        heading = re.match(r"^##\s+([A-Za-z0-9_-]+)/(FN-[0-9]+)\s+(.+?)\s*$", line.strip())
        if heading:
            flush_current()
            current_key = (heading.group(1), heading.group(2))
            current_lines = []
            continue
        if current_key:
            current_lines.append(line)
    flush_current()

    _DASHBOARD_COPY_CACHE["mtime"] = mtime
    _DASHBOARD_COPY_CACHE["data"] = parsed
    return parsed


def _dashboard_copy_for(module: str, fn_id: str) -> dict[str, Any]:
    return _parse_dashboard_copy_doc().get((module, fn_id), {})


def _parse_performance_copy_doc() -> dict[tuple[str, str], dict[str, Any]]:
    try:
        mtime = PERFORMANCE_DASHBOARD_COPY_DOC.stat().st_mtime
    except OSError:
        _PERFORMANCE_COPY_CACHE["mtime"] = -1.0
        _PERFORMANCE_COPY_CACHE["data"] = {}
        return {}
    if _PERFORMANCE_COPY_CACHE.get("mtime") == mtime:
        data = _PERFORMANCE_COPY_CACHE.get("data")
        return data if isinstance(data, dict) else {}

    text = _read_text(PERFORMANCE_DASHBOARD_COPY_DOC, 2 * 1024 * 1024)
    parsed: dict[tuple[str, str], dict[str, Any]] = {}
    current_key: tuple[str, str] | None = None
    current_lines: list[str] = []

    def flush_current():
        if not current_key:
            return
        block = "\n".join(current_lines)
        goal = _dashboard_subsection(block, "验证目标")
        implementation = _dashboard_subsection(block, "实现方案")
        test_section = _dashboard_subsection(block, "测试方案")
        item = {
            "goal": goal,
            "implementation": implementation,
            "prerequisites": _dashboard_named_list(test_section, "前置条件"),
            "test_plan": _dashboard_named_list(test_section, "测试方案"),
            "source_doc": _rel_path(PERFORMANCE_DASHBOARD_COPY_DOC),
        }
        if goal or implementation or item["prerequisites"] or item["test_plan"]:
            parsed[current_key] = item

    for line in _dashboard_lines(text):
        heading = re.match(r"^##\s+([A-Za-z0-9_-]+)/(PF-[0-9]+)\s+(.+?)\s*$", line.strip())
        if heading:
            flush_current()
            current_key = (heading.group(1), heading.group(2))
            current_lines = []
            continue
        if current_key:
            current_lines.append(line)
    flush_current()

    _PERFORMANCE_COPY_CACHE["mtime"] = mtime
    _PERFORMANCE_COPY_CACHE["data"] = parsed
    return parsed


def _performance_copy_for(module: str, pf_id: str) -> dict[str, Any]:
    return _parse_performance_copy_doc().get((module, pf_id), {})


def _latest_child(parent: Path, prefix: str) -> Path | None:
    if not parent.exists():
        return None
    candidates = [
        p for p in parent.iterdir()
        if p.is_dir() and p.name.startswith(prefix)
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def _summary_result_source(parent: Path, prefix: str, fallback_dir: Path) -> tuple[Path, str]:
    hist = _latest_child(parent, prefix)
    if hist and ((hist / "raw.json").exists() or (hist / "summary.md").exists()):
        return hist, "前端执行历史"
    return fallback_dir, "基线结果"


def _parse_result_time(value: Any) -> float:
    text = str(value or "")
    if not text:
        return 0.0
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d %H:%M:%S"):
        try:
            return time.mktime(time.strptime(text, fmt))
        except Exception:
            pass
    return 0.0


def _result_mtime(path: Path | None) -> float:
    if not path:
        return 0.0
    try:
        if path.is_dir():
            candidates = [path / "raw.json", path / "summary.md", path]
        else:
            candidates = [path]
        return max(p.stat().st_mtime for p in candidates if p.exists())
    except Exception:
        return 0.0


def _result_sort_key(raw: dict[str, Any], source_path: Path | None) -> tuple[float, float]:
    result_time = _parse_result_time(raw.get("finished_at") or raw.get("generated_at"))
    mtime = _result_mtime(source_path)
    return (result_time or mtime, mtime)


def _status_text(status: Any) -> str:
    s = str(status or "").upper()
    if s == "WAIVED":
        return "跳过"
    return _FUNCTION_STATUS_TEXT.get(s, "未知")


def _completion_attention(completion: Any) -> bool:
    return str(completion or "") in {"部分完成", "未完成"}


def _latest_function_history(module: str, fn_id: str) -> tuple[dict[str, Any], str, str, str]:
    fn_dir = FUNCTIONS_DIR / module / fn_id
    hist_dir = _latest_child(fn_dir / "history", "web_")
    if hist_dir and ((hist_dir / "raw.json").exists() or (hist_dir / "summary.md").exists()):
        raw = _read_json(hist_dir / "raw.json")
        return raw if isinstance(raw, dict) else {}, str(hist_dir), "前端执行历史", _read_text(hist_dir / "summary.md")
    return {}, "", "", ""


def _latest_function_result(
    module: str,
    fn_id: str,
    run_all_row: dict[str, Any] | None = None,
    run_all_source_dir: Path | None = None,
    run_all_source_label: str = "",
    run_all_summary_md: str = "",
) -> tuple[dict[str, Any], str, str, str]:
    fn_dir = FUNCTIONS_DIR / module / fn_id
    candidates: list[tuple[tuple[float, float], dict[str, Any], str, str, str]] = []

    baseline_raw = _read_json(fn_dir / "raw.json")
    if isinstance(baseline_raw, dict) and baseline_raw:
        candidates.append((
            _result_sort_key(baseline_raw, fn_dir / "raw.json"),
            baseline_raw,
            "",
            "基线结果",
            _read_text(fn_dir / "summary.md"),
        ))

    hist_raw, hist_dir, hist_source, hist_summary = _latest_function_history(module, fn_id)
    if hist_raw:
        hist_path = Path(hist_dir) if hist_dir else None
        candidates.append((
            _result_sort_key(hist_raw, hist_path),
            hist_raw,
            hist_dir,
            hist_source,
            hist_summary,
        ))

    if run_all_row:
        candidates.append((
            _result_sort_key(run_all_row, run_all_source_dir),
            run_all_row,
            str(run_all_source_dir) if run_all_source_label == "前端执行历史" and run_all_source_dir else "",
            run_all_source_label or "基线结果",
            run_all_summary_md,
        ))

    if not candidates:
        return {}, "", "基线结果", ""
    _key, raw, source_dir, source_label, summary = max(candidates, key=lambda item: item[0])
    return raw, source_dir, source_label, summary


def _performance_status(raw: dict[str, Any]) -> str:
    if not raw:
        return "SKIP"
    return "PASS" if bool(raw.get("passed", False)) else "FAIL"


def _perf_fmt(value: Any, suffix: str = "") -> str:
    if value is None or value == "":
        return "N/A"
    if isinstance(value, float):
        text = f"{value:.3f}".rstrip("0").rstrip(".")
    else:
        text = str(value)
    return f"{text}{suffix}"


def _performance_key_result(pf_id: str, raw: dict[str, Any]) -> str:
    if pf_id == "PF-1":
        return f"吞吐 {_perf_fmt(raw.get('ops_per_sec'), ' ops/s')}，带宽利用率 {_perf_fmt(raw.get('bw_util_pct'), '%')}"
    if pf_id == "PF-2":
        return f"avg {_perf_fmt(raw.get('lat_avg_us'), 'us')}，P99 {_perf_fmt(raw.get('lat_p99_us'), 'us')}"
    if pf_id == "PF-3":
        return f"提升 {_perf_fmt(raw.get('gain_pct'), '%')}"
    if pf_id == "PF-4":
        a = raw.get("scenario_a") if isinstance(raw.get("scenario_a"), dict) else {}
        b = raw.get("scenario_b") if isinstance(raw.get("scenario_b"), dict) else {}
        return f"A {_perf_fmt(a.get('elapsed_ms'), 'ms')}，B {_perf_fmt(b.get('elapsed_ms'), 'ms')}"
    if pf_id == "PF-5":
        return f"{_perf_fmt(raw.get('mb_per_sec'), ' MB/s')}"
    if pf_id == "PF-6":
        return f"写 {_perf_fmt(raw.get('write_gbs'), ' GB/s')}，读 {_perf_fmt(raw.get('read_gbs'), ' GB/s')}"
    if pf_id == "PF-7":
        return f"P999 {_perf_fmt(raw.get('lat_p999_us'), 'us')}，RAID5 {_perf_fmt(raw.get('raid5_confirmed'))}"
    if pf_id == "PF-8":
        return f"speedup {_perf_fmt(raw.get('speedup'), 'x')}，events/s {_perf_fmt(raw.get('events_per_sec'))}"
    if pf_id == "PF-9":
        return (
            f"损失 {_perf_fmt(raw.get('overhead_pct'), '%')}，"
            f"节省 {_perf_fmt(raw.get('savings_pct'), '%')}，"
            f"提升 {_perf_fmt(raw.get('scale_gain_pct'), '%')}"
        )
    return "N/A"


def _performance_evidence(pf_id: str, raw: dict[str, Any]) -> list[str]:
    if not raw:
        return ["暂无原始性能结果"]
    base = [_performance_key_result(pf_id, raw)]
    if pf_id == "PF-1":
        base.extend([
            f"ops_fail={raw.get('ops_fail', 'N/A')}，ops_degraded={raw.get('ops_degraded', 'N/A')}",
            f"bw_fail={raw.get('bw_fail', 'N/A')}，bw_degraded={raw.get('bw_degraded', 'N/A')}",
        ])
    elif pf_id == "PF-2":
        base.append(f"samples={raw.get('samples', 'N/A')}，fail={raw.get('ops_fail', 'N/A')}，degraded={raw.get('ops_degraded', 'N/A')}")
    elif pf_id == "PF-3":
        base.append(f"hi_ops={raw.get('hi_ops', 'N/A')}，lo_ops={raw.get('lo_ops', 'N/A')}，qos_mode={raw.get('qos_mode', 'N/A')}")
    elif pf_id == "PF-4":
        base.append(f"scenario_a_pass={raw.get('passed_a', 'N/A')}，scenario_b_pass={raw.get('passed_b', 'N/A')}")
    elif pf_id == "PF-5":
        base.append(f"ops={raw.get('ops_per_sec', 'N/A')}，fail={raw.get('ops_fail', 'N/A')}，degraded={raw.get('ops_degraded', 'N/A')}")
    elif pf_id == "PF-6":
        base.append(f"read_hit_ratio={raw.get('read_hit_ratio', 'N/A')}，write_fail={raw.get('write_fail', 'N/A')}，read_fail={raw.get('read_fail', 'N/A')}")
    elif pf_id == "PF-7":
        base.append(f"success_writes={raw.get('success_writes', 'N/A')}，failed_writes={raw.get('failed_writes', 'N/A')}，backend={raw.get('backend', 'N/A')}")
    elif pf_id == "PF-8":
        base.append(f"entities={raw.get('entities', 'N/A')}，events={raw.get('events', 'N/A')}，dropped={raw.get('captured_dropped', 'N/A')}")
    elif pf_id == "PF-9":
        base.append(f"threads={raw.get('threads_multi', 'N/A')}，malloc_rss={raw.get('malloc_live_rss_kb', 'N/A')}KB，slab_rss={raw.get('slab_live_rss_kb', 'N/A')}KB")
    return base


def _latest_performance_history(pf_id: str) -> tuple[dict[str, Any], str, str, str]:
    pf_dir = PERFORMANCES_DIR / pf_id
    hist_dir = _latest_child(pf_dir / "history", "web_")
    if hist_dir and ((hist_dir / "raw.json").exists() or (hist_dir / "summary.md").exists()):
        raw = _read_json(hist_dir / "raw.json")
        return raw if isinstance(raw, dict) else {}, str(hist_dir), "前端执行历史", _read_text(hist_dir / "summary.md")
    return {}, "", "", ""


def _latest_performance_result(pf_id: str) -> tuple[dict[str, Any], str, str, str]:
    pf_dir = PERFORMANCES_DIR / pf_id
    candidates: list[tuple[tuple[float, float], dict[str, Any], str, str, str]] = []

    baseline_raw = _read_json(pf_dir / "raw.json")
    if isinstance(baseline_raw, dict) and baseline_raw:
        candidates.append((
            _result_sort_key(baseline_raw, pf_dir / "raw.json"),
            baseline_raw,
            "",
            "基线结果",
            _read_text(pf_dir / "summary.md"),
        ))

    hist_raw, hist_dir, hist_source, hist_summary = _latest_performance_history(pf_id)
    if hist_raw:
        hist_path = Path(hist_dir) if hist_dir else None
        candidates.append((
            _result_sort_key(hist_raw, hist_path),
            hist_raw,
            hist_dir,
            hist_source,
            hist_summary,
        ))

    if not candidates:
        return {}, "", "基线结果", ""
    _key, raw, source_dir, source_label, summary = max(candidates, key=lambda item: item[0])
    return raw, source_dir, source_label, summary


def _build_performance_summary_payload() -> dict[str, Any]:
    totals = {"total": 0, "PASS": 0, "FAIL": 0, "SKIP": 0, "WAIVED": 0}
    execution_totals = {"total": 0, "executed": 0, "pending": 0, "PASS": 0, "FAIL": 0, "SKIP": 0, "WAIVED": 0}
    modules: dict[str, Any] = {}
    output_rows = []
    generated_at = ""
    latest_mtime = 0.0
    for module, info in _PERFORMANCE_MODULES.items():
        counts = {"PASS": 0, "FAIL": 0, "SKIP": 0, "WAIVED": 0}
        execution_counts = {"PASS": 0, "FAIL": 0, "SKIP": 0, "WAIVED": 0}
        executed_count = 0
        functions = []
        for pf_id, name in info["functions"]:
            raw, history_dir, row_source, row_summary = _latest_performance_result(pf_id)
            status = _performance_status(raw)
            counts[status] += 1
            totals[status] += 1
            totals["total"] += 1
            execution_totals["total"] += 1
            executed = row_source == "前端执行历史"
            if executed:
                executed_count += 1
                execution_totals["executed"] += 1
                execution_totals[status] += 1
                execution_counts[status] += 1
            else:
                execution_totals["pending"] += 1
            item = {
                "module": module,
                "fn_id": pf_id,
                "function_display_name": name,
                "status": status,
                "status_text": _status_text(status),
                "display_status_text": _status_text(status),
                "executed": executed,
                "completion": "完成" if status == "PASS" else "未完成",
                "attention": status != "PASS",
                "evidence": _performance_evidence(pf_id, raw),
                "result_source": row_source,
                "history_dir": _rel_path(history_dir) if history_dir else "",
                "summary_md": row_summary,
            }
            functions.append(item)
            output_rows.append(item)
            row_generated = str(raw.get("generated_at") or raw.get("finished_at") or "")
            if row_generated > generated_at:
                generated_at = row_generated
            try:
                source_path = Path(history_dir) if history_dir else (PERFORMANCES_DIR / pf_id / "raw.json")
                latest_mtime = max(latest_mtime, _result_mtime(source_path))
            except Exception:
                pass
        modules[module] = {
            "display_name": info["display_name"],
            "total": info["count"],
            "status_counts": counts,
            "status_counts_text": {_status_text(k): v for k, v in counts.items()},
            "execution_counts": execution_counts,
            "execution_counts_text": {_status_text(k): v for k, v in execution_counts.items()},
            "executed": executed_count,
            "pending": info["count"] - executed_count,
            "functions": functions,
        }
    if not generated_at and latest_mtime:
        generated_at = time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(latest_mtime))
    return {
        "ok": True,
        "generated_at": generated_at,
        "totals": totals,
        "execution_totals": execution_totals,
        "modules": modules,
        "rows": output_rows,
        "summary_md": _read_text(PERFORMANCES_DIR / "summary.md"),
        "result_source": "前端执行历史" if any(item["history_dir"] for item in output_rows) else "基线结果",
        "history_dir": "",
    }


def _build_summary_payload() -> dict[str, Any]:
    source_dir, result_source = _summary_result_source(
        FUNCTIONS_DIR / "history", "web_all_", FUNCTIONS_DIR)
    raw = _read_json(source_dir / "raw.json")
    summary_md = _read_text(source_dir / "summary.md")
    run_all_rows = raw.get("rows", []) if isinstance(raw, dict) else []
    rows_by_key = {
        (str(row.get("module")), str(row.get("fn_id"))): row
        for row in run_all_rows if isinstance(row, dict)
    }
    totals = {"total": 0, "PASS": 0, "FAIL": 0, "SKIP": 0, "WAIVED": 0}
    execution_totals = {"total": 0, "executed": 0, "pending": 0, "PASS": 0, "FAIL": 0, "SKIP": 0, "WAIVED": 0}
    modules: dict[str, Any] = {}
    output_rows = []
    generated_at = str(raw.get("generated_at", "")) if isinstance(raw, dict) else ""
    latest_mtime = 0.0
    for module, info in _FUNCTION_MODULES.items():
        counts = {"PASS": 0, "FAIL": 0, "SKIP": 0, "WAIVED": 0}
        execution_counts = {"PASS": 0, "FAIL": 0, "SKIP": 0, "WAIVED": 0}
        executed_count = 0
        functions = []
        for fn_id, name in info["functions"]:
            row, history_dir, row_source, row_summary = _latest_function_result(
                module,
                fn_id,
                rows_by_key.get((module, fn_id), {}),
                source_dir,
                result_source,
                summary_md,
            )
            status = str(row.get("status", "SKIP")).upper()
            if status == "WAIVED":
                status = "SKIP"
            if status not in counts:
                status = "FAIL"
            completion = row.get("completion", "未完成")
            counts[status] += 1
            totals[status] += 1
            totals["total"] += 1
            execution_totals["total"] += 1
            row_generated = str(row.get("finished_at") or row.get("generated_at") or "")
            if row_generated > generated_at:
                generated_at = row_generated
            history_exists = bool(history_dir)
            executed = row_source == "前端执行历史"
            if executed:
                executed_count += 1
                execution_totals["executed"] += 1
                execution_totals[status] += 1
                execution_counts[status] += 1
            else:
                execution_totals["pending"] += 1
            item = {
                "module": module,
                "fn_id": fn_id,
                "function_display_name": name,
                "status": status,
                "status_text": _status_text(status),
                "display_status_text": _status_text(status),
                "executed": executed,
                "completion": completion,
                "attention": status in {"FAIL", "SKIP", "WAIVED"} or _completion_attention(completion),
                "evidence": row.get("evidence", []),
                "result_source": row_source,
                "history_dir": _rel_path(history_dir) if history_dir else "",
                "summary_md": row_summary,
            }
            functions.append(item)
            output_rows.append(item)
            if history_exists:
                try:
                    latest_mtime = max(latest_mtime, Path(history_dir).stat().st_mtime)
                except Exception:
                    pass
        modules[module] = {
            "display_name": info["display_name"],
            "total": info["count"],
            "status_counts": counts,
            "status_counts_text": {_status_text(k): v for k, v in counts.items()},
            "execution_counts": execution_counts,
            "execution_counts_text": {_status_text(k): v for k, v in execution_counts.items()},
            "executed": executed_count,
            "pending": info["count"] - executed_count,
            "functions": functions,
        }
    if not generated_at and latest_mtime:
        generated_at = time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(latest_mtime))
    elif not generated_at:
        generated_at = raw.get("generated_at", "") if isinstance(raw, dict) else ""
    return {
        "ok": True,
        "generated_at": generated_at,
        "totals": totals,
        "execution_totals": execution_totals,
        "modules": modules,
        "rows": output_rows,
        "summary_md": summary_md,
        "result_source": "前端执行历史" if any(item["history_dir"] for item in output_rows) or result_source == "前端执行历史" else "基线结果",
        "history_dir": _rel_path(source_dir) if result_source == "前端执行历史" else "",
    }


@app.route("/api/functions/summary")
def functions_summary():
    return jsonify(_build_summary_payload())


@app.route("/api/functions/fn/<module>/<fn_id>")
def functions_fn(module, fn_id):
    try:
        fn_dir = _safe_fn_dir(module, fn_id)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 404
    raw, history_dir, result_source, result_summary_md = _latest_function_result(module, fn_id)
    logs_dir = fn_dir / "logs"
    logs = []
    if logs_dir.exists():
        for p in sorted(logs_dir.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True)[:40]:
            if p.is_file():
                st = p.stat()
                logs.append({"name": p.name, "size": st.st_size, "mtime": st.st_mtime})
    status = str(raw.get("status", "SKIP")).upper() if isinstance(raw, dict) else "SKIP"
    if status == "WAIVED":
        status = "SKIP"
    if status not in _FUNCTION_STATUS_TEXT:
        status = "FAIL"
    return jsonify({
        "ok": True,
        "module": module,
        "fn_id": fn_id,
        "module_display_name": _FUNCTION_MODULES[module]["display_name"],
        "function_display_name": _display_name(module, fn_id),
        "status": status,
        "status_text": _status_text(status),
        "completion": raw.get("completion", "") if isinstance(raw, dict) else "",
        "dashboard_copy": _dashboard_copy_for(module, fn_id),
        "fn_md": _read_text(fn_dir / f"{fn_id}.md"),
        "summary_md": result_summary_md or _read_text(fn_dir / "summary.md"),
        "raw": raw,
        "run_sh": _read_text(fn_dir / "run.sh"),
        "run_py": _read_text(fn_dir / "run.py"),
        "result_source": result_source,
        "history_dir": _rel_path(history_dir) if result_source == "前端执行历史" and history_dir else "",
        "logs": logs,
    })


@app.route("/api/functions/fn/<module>/<fn_id>/file")
def functions_fn_file(module, fn_id):
    try:
        fn_dir = _safe_fn_dir(module, fn_id)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 404
    name = request.args.get("name", "")
    allowed = {f"{fn_id}.md", "summary.md", "raw.json", "run.sh", "run.py"}
    if name not in allowed:
        return jsonify({"ok": False, "error": "文件不在允许列表"}), 400
    return jsonify({"ok": True, "name": name, "content": _read_text(fn_dir / name)})


@app.route("/api/functions/fn/<module>/<fn_id>/log")
def functions_fn_log(module, fn_id):
    try:
        fn_dir = _safe_fn_dir(module, fn_id)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 404
    name = request.args.get("name", "")
    if not name or "/" in name or "\\" in name:
        return jsonify({"ok": False, "error": "日志名非法"}), 400
    logs_dir = (fn_dir / "logs").resolve()
    path = (logs_dir / name).resolve()
    if not str(path).startswith(str(logs_dir) + os.sep) or not path.is_file():
        return jsonify({"ok": False, "error": "日志不存在"}), 404
    try:
        tail_bytes = int(request.args.get("tail_bytes", "65536"))
    except ValueError:
        tail_bytes = 65536
    tail_bytes = max(1, min(1024 * 1024, tail_bytes))
    size = path.stat().st_size
    with open(path, "rb") as f:
        if size > tail_bytes:
            f.seek(size - tail_bytes)
        data = f.read()
    return jsonify({
        "ok": True,
        "name": name,
        "truncated": size > tail_bytes,
        "content": data.decode("utf-8", errors="replace"),
    })


def _sanitize_function_env(body_env: Any, *, module: str = "", fn_id: str = "") -> dict[str, str]:
    env = dict(_FUNCTION_DEFAULT_ENV)
    if isinstance(body_env, dict):
        for key, value in body_env.items():
            if key in _FUNCTION_ALLOWED_ENV:
                env[key] = str(value)
    if env.get("ALLOW_DESTRUCTIVE") not in {"1", "true", "True"}:
        env["ALLOW_DESTRUCTIVE"] = "0"
    else:
        complete_peer = all(env.get(k) for k in ("PEER_SSH", "PEER_DP_PATH", "PEER_START_CMD"))
        if module != "mempool" or fn_id != "FN-6" or not complete_peer:
            raise ValueError("破坏性 HA 演练默认禁用，且仅允许 mempool 高可靠功能点携带完整 peer 参数后执行")
    return env


def _new_job_id(prefix: str) -> str:
    return f"{prefix}_{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"


def _write_job_metadata(job: dict[str, Any]) -> None:
    meta = {
        k: v for k, v in job.items()
        if k not in {"thread", "process"}
    }
    try:
        (Path(job["history_abs"]) / "metadata.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8")
    except Exception:
        pass


def _active_function_job_exists() -> bool:
    return any(job.get("state") in {"queued", "running"} for job in _FUNCTION_JOBS.values())


def _prepare_job(kind: str, env: dict[str, str], module: str = "", fn_id: str = "") -> dict[str, Any]:
    prefix = "fn_all" if kind == "run_all" else f"fn_{module}_{fn_id.replace('-', '')}"
    job_id = _new_job_id(prefix)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    if kind == "run_all":
        history_abs = FUNCTIONS_DIR / "history" / f"web_all_{stamp}_{job_id}"
    else:
        history_abs = FUNCTIONS_DIR / module / fn_id / "history" / f"web_{stamp}_{job_id}"
    history_abs.mkdir(parents=True, exist_ok=True)
    job = {
        "ok": True,
        "job_id": job_id,
        "kind": kind,
        "module": module,
        "fn_id": fn_id,
        "state": "queued",
        "exit_code": None,
        "started_at": "",
        "finished_at": None,
        "error": "",
        "history_abs": str(history_abs),
        "history_dir": _rel_path(history_abs),
        "job_log": _rel_path(history_abs / "stdout.log"),
        "env": {k: env.get(k, "") for k in _FUNCTION_ALLOWED_ENV if k in env},
    }
    _FUNCTION_JOBS[job_id] = job
    _write_job_metadata(job)
    return job


def _copy_if_exists(src: Path, dst: Path) -> None:
    if src.exists() and src.is_file():
        if src.resolve() == dst.resolve():
            return
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


def _restore_baseline(saved: dict[Path, bytes | None]) -> None:
    for path, data in saved.items():
        if data is None:
            try:
                path.unlink()
            except FileNotFoundError:
                pass
        else:
            path.write_bytes(data)


def _run_function_job(job_id: str, cmd: list[str], cwd: Path, env: dict[str, str],
                      protected_files: list[Path], result_files: list[tuple[Path, str]]) -> None:
    job = _FUNCTION_JOBS[job_id]
    hist = Path(job["history_abs"])
    stdout_log = hist / "stdout.log"
    saved = {p: (p.read_bytes() if p.exists() else None) for p in protected_files}
    run_env = os.environ.copy()
    run_env.update(env)
    run_env["REPO_ROOT"] = str(REPO_ROOT)
    run_env.setdefault("PYTHONUNBUFFERED", "1")
    with _FUNCTION_RUN_LOCK:
        if job.get("state") == "failed":
            return
        with _FUNCTION_JOB_LOCK:
            job["state"] = "running"
            job["started_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
            _write_job_metadata(job)
        try:
            with open(stdout_log, "w", encoding="utf-8", errors="replace") as out:
                out.write("Command: " + " ".join(cmd) + "\n\n")
                out.flush()
                proc = subprocess.Popen(
                    cmd,
                    cwd=str(cwd),
                    env=run_env,
                    stdout=out,
                    stderr=subprocess.STDOUT,
                    text=True,
                )
                job["process"] = proc
                rc = proc.wait()
            with _FUNCTION_JOB_LOCK:
                job["exit_code"] = rc
                job["state"] = "finished" if rc == 0 else "failed"
            for src, name in result_files:
                _copy_if_exists(src, hist / name)
            if not (hist / "summary.md").exists():
                for src in protected_files:
                    if src.name == "summary.md":
                        _copy_if_exists(src, hist / "summary.md")
                        break
            if not (hist / "raw.json").exists():
                for src in protected_files:
                    if src.name == "raw.json":
                        _copy_if_exists(src, hist / "raw.json")
                        break
            for p in hist.glob("logs/run_*.log"):
                _copy_if_exists(p, hist / "run.log")
            for p in hist.glob("logs/run_*.json"):
                _copy_if_exists(p, hist / "run.json")
            for p in hist.glob("logs/run_all_*.log"):
                _copy_if_exists(p, hist / "run_all.log")
        except Exception as exc:
            with _FUNCTION_JOB_LOCK:
                job["state"] = "failed"
                job["error"] = str(exc)
            with open(stdout_log, "a", encoding="utf-8", errors="replace") as out:
                out.write(f"\n[function-dashboard] job failed: {exc}\n")
        finally:
            _restore_baseline(saved)
            with _FUNCTION_JOB_LOCK:
                job["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
                _write_job_metadata(job)


@app.route("/api/functions/run_one", methods=["POST"])
def functions_run_one():
    body = request.get_json(force=True) or {}
    module = str(body.get("module", ""))
    fn_id = str(body.get("fn_id", ""))
    try:
        fn_dir = _safe_fn_dir(module, fn_id)
        env = _sanitize_function_env(body.get("env", {}), module=module, fn_id=fn_id)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    with _FUNCTION_JOB_LOCK:
        if _active_function_job_exists():
            return jsonify({"ok": False, "error": "已有功能验收任务正在执行"}), 409
        job = _prepare_job("run_one", env, module, fn_id)
    hist = Path(job["history_abs"])
    run_env = dict(env)
    run_env["OUT_DIR"] = str(hist)
    run_env["LOG_DIR"] = str(hist / "logs")
    run_env["RUN_TS"] = time.strftime("%Y%m%d_%H%M%S")
    cmd = ["bash", str(fn_dir / "run.sh")]
    protected = [fn_dir / "summary.md", fn_dir / "raw.json"]
    results = [(hist / "summary.md", "summary.md"), (hist / "raw.json", "raw.json")]
    th = threading.Thread(
        target=_run_function_job,
        args=(job["job_id"], cmd, fn_dir, run_env, protected, results),
        daemon=True,
    )
    job["thread"] = th
    th.start()
    return jsonify({"ok": True, "job_id": job["job_id"], "history_dir": job["history_dir"]})


@app.route("/api/functions/run_all", methods=["POST"])
def functions_run_all():
    body = request.get_json(force=True) or {}
    try:
        env = _sanitize_function_env(body.get("env", {}))
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    with _FUNCTION_JOB_LOCK:
        if _active_function_job_exists():
            return jsonify({"ok": False, "error": "已有功能验收任务正在执行"}), 409
        job = _prepare_job("run_all", env)
    hist = Path(job["history_abs"])
    run_env = dict(env)
    run_all_ts = time.strftime("%Y%m%d_%H%M%S")
    run_env["RUN_ALL_TS"] = run_all_ts
    cmd = ["bash", str(FUNCTIONS_DIR / "run_all.sh")]
    protected = [FUNCTIONS_DIR / "summary.md", FUNCTIONS_DIR / "raw.json"]
    for module, info in _FUNCTION_MODULES.items():
        for fn_id, _ in info["functions"]:
            protected.extend([
                FUNCTIONS_DIR / module / fn_id / "summary.md",
                FUNCTIONS_DIR / module / fn_id / "raw.json",
            ])
    results = [
        (FUNCTIONS_DIR / "summary.md", "summary.md"),
        (FUNCTIONS_DIR / "raw.json", "raw.json"),
        (FUNCTIONS_DIR / "logs" / f"run_all_{run_all_ts}.log", "run_all.log"),
        (FUNCTIONS_DIR / "logs" / f"run_all_{run_all_ts}.stdio.log", "run_all.stdio.log"),
    ]
    th = threading.Thread(
        target=_run_function_job,
        args=(job["job_id"], cmd, FUNCTIONS_DIR, run_env, protected, results),
        daemon=True,
    )
    job["thread"] = th
    th.start()
    return jsonify({"ok": True, "job_id": job["job_id"], "history_dir": job["history_dir"]})


@app.route("/api/functions/jobs/<job_id>")
def functions_job(job_id):
    job = _FUNCTION_JOBS.get(job_id)
    if not job:
        return jsonify({"ok": False, "error": "任务不存在"}), 404
    stdout_log = Path(job["history_abs"]) / "stdout.log"
    stdout_tail = ""
    if stdout_log.exists():
        size = stdout_log.stat().st_size
        with open(stdout_log, "rb") as f:
            if size > 65536:
                f.seek(size - 65536)
            stdout_tail = f.read().decode("utf-8", errors="replace")
    out = {
        k: v for k, v in job.items()
        if k not in {"thread", "process", "history_abs"}
    }
    out["stdout_tail"] = stdout_tail
    return jsonify(out)


@app.route("/api/performance/summary")
def performance_summary():
    return jsonify(_build_performance_summary_payload())


@app.route("/api/performance/fn/<module>/<pf_id>")
def performance_fn(module, pf_id):
    try:
        pf_dir = _safe_pf_dir(module, pf_id)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 404
    raw, history_dir, result_source, result_summary_md = _latest_performance_result(pf_id)
    raw = raw if isinstance(raw, dict) else {}
    status = _performance_status(raw)
    logs_dir = pf_dir / "logs"
    logs = []
    if logs_dir.exists():
        for p in sorted(logs_dir.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True)[:40]:
            if p.is_file():
                st = p.stat()
                logs.append({"name": p.name, "size": st.st_size, "mtime": st.st_mtime})
    return jsonify({
        "ok": True,
        "module": module,
        "fn_id": pf_id,
        "module_display_name": _PERFORMANCE_MODULES[module]["display_name"],
        "function_display_name": _performance_display_name(module, pf_id),
        "status": status,
        "status_text": _status_text(status),
        "completion": "完成" if status == "PASS" else "未完成",
        "dashboard_copy": _performance_copy_for(module, pf_id),
        "fn_md": _read_text(pf_dir / f"{pf_id}.md"),
        "summary_md": result_summary_md or _read_text(pf_dir / "summary.md"),
        "raw": raw,
        "evidence": _performance_evidence(pf_id, raw),
        "run_sh": _read_text(pf_dir / "run.sh"),
        "run_py": _read_text(pf_dir / "run.py"),
        "result_source": result_source,
        "history_dir": _rel_path(history_dir) if result_source == "前端执行历史" and history_dir else "",
        "logs": logs,
    })


@app.route("/api/performance/fn/<module>/<pf_id>/file")
def performance_fn_file(module, pf_id):
    try:
        pf_dir = _safe_pf_dir(module, pf_id)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 404
    name = request.args.get("name", "")
    allowed = {f"{pf_id}.md", "summary.md", "raw.json", "run.sh", "run.py"}
    if name not in allowed:
        return jsonify({"ok": False, "error": "文件不在允许列表"}), 400
    return jsonify({"ok": True, "name": name, "content": _read_text(pf_dir / name)})


@app.route("/api/performance/fn/<module>/<pf_id>/log")
def performance_fn_log(module, pf_id):
    try:
        pf_dir = _safe_pf_dir(module, pf_id)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 404
    name = request.args.get("name", "")
    if not name or "/" in name or "\\" in name:
        return jsonify({"ok": False, "error": "日志名非法"}), 400
    logs_dir = (pf_dir / "logs").resolve()
    path = (logs_dir / name).resolve()
    if not str(path).startswith(str(logs_dir) + os.sep) or not path.is_file():
        return jsonify({"ok": False, "error": "日志不存在"}), 404
    try:
        tail_bytes = int(request.args.get("tail_bytes", "65536"))
    except ValueError:
        tail_bytes = 65536
    tail_bytes = max(1, min(1024 * 1024, tail_bytes))
    size = path.stat().st_size
    with open(path, "rb") as f:
        if size > tail_bytes:
            f.seek(size - tail_bytes)
        data = f.read()
    return jsonify({
        "ok": True,
        "name": name,
        "truncated": size > tail_bytes,
        "content": data.decode("utf-8", errors="replace"),
    })


def _sanitize_performance_env(body_env: Any) -> dict[str, str]:
    env = dict(_PERFORMANCE_DEFAULT_ENV)
    if isinstance(body_env, dict):
        for key, value in body_env.items():
            if key in _PERFORMANCE_ALLOWED_ENV:
                env[key] = str(value)
    return env


def _active_performance_job_exists() -> bool:
    return any(job.get("state") in {"queued", "running"} for job in _PERFORMANCE_JOBS.values())


def _prepare_performance_job(kind: str, env: dict[str, str], module: str = "", pf_id: str = "") -> dict[str, Any]:
    prefix = "pf_all" if kind == "run_all" else f"pf_{pf_id.replace('-', '')}"
    job_id = _new_job_id(prefix)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    if kind == "run_all":
        history_abs = PERFORMANCES_DIR / "history" / f"web_all_{stamp}_{job_id}"
    else:
        history_abs = PERFORMANCES_DIR / pf_id / "history" / f"web_{stamp}_{job_id}"
    history_abs.mkdir(parents=True, exist_ok=True)
    job = {
        "ok": True,
        "job_id": job_id,
        "kind": kind,
        "module": module,
        "fn_id": pf_id,
        "state": "queued",
        "exit_code": None,
        "started_at": "",
        "finished_at": None,
        "error": "",
        "history_abs": str(history_abs),
        "history_dir": _rel_path(history_abs),
        "job_log": _rel_path(history_abs / "stdout.log"),
        "env": {k: env.get(k, "") for k in _PERFORMANCE_ALLOWED_ENV if k in env},
    }
    _PERFORMANCE_JOBS[job_id] = job
    _write_job_metadata(job)
    return job


def _copy_performance_run_all_results(job: dict[str, Any]) -> None:
    hist = Path(job["history_abs"])
    _copy_if_exists(PERFORMANCES_DIR / "summary.md", hist / "summary.md")
    for pf_id, _name in _PERFORMANCE_MODULES["performance"]["functions"]:
        pf_dir = PERFORMANCES_DIR / pf_id
        pf_hist = pf_dir / "history" / f"web_all_{hist.name.removeprefix('web_all_')}"
        pf_hist.mkdir(parents=True, exist_ok=True)
        _copy_if_exists(pf_dir / "summary.md", pf_hist / "summary.md")
        _copy_if_exists(pf_dir / "raw.json", pf_hist / "raw.json")
        _copy_if_exists(pf_dir / "run_all.last.log", pf_hist / "run_all.last.log")


def _recover_performance_job(job_id: str) -> dict[str, Any] | None:
    try:
        matches = sorted(PERFORMANCES_DIR.glob(f"**/history/*{job_id}/metadata.json"))
    except Exception:
        matches = []
    if not matches:
        return None
    meta_path = matches[-1]
    meta = _read_json(meta_path)
    if not isinstance(meta, dict):
        return None
    hist = meta_path.parent
    raw = _read_json(hist / "raw.json")
    if isinstance(raw, dict) and raw:
        meta["state"] = "finished" if bool(raw.get("passed", False)) else "failed"
        meta["exit_code"] = 0 if bool(raw.get("passed", False)) else 1
        meta["finished_at"] = meta.get("finished_at") or time.strftime(
            "%Y-%m-%dT%H:%M:%S%z", time.localtime(_result_mtime(hist / "raw.json")))
    elif (hist / "summary.md").exists() and meta.get("state") == "running":
        meta["state"] = "finished"
        meta["exit_code"] = 0
        meta["finished_at"] = meta.get("finished_at") or time.strftime(
            "%Y-%m-%dT%H:%M:%S%z", time.localtime(_result_mtime(hist / "summary.md")))
    meta["history_abs"] = str(hist)
    meta["history_dir"] = _rel_path(hist)
    meta.setdefault("job_log", _rel_path(hist / "stdout.log"))
    try:
        meta_path.write_text(
            json.dumps({k: v for k, v in meta.items() if k != "history_abs"}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8")
    except Exception:
        pass
    return meta


def _run_performance_job(job_id: str, cmd: list[str], cwd: Path, env: dict[str, str],
                         protected_files: list[Path], result_files: list[tuple[Path, str]]) -> None:
    job = _PERFORMANCE_JOBS[job_id]
    hist = Path(job["history_abs"])
    stdout_log = hist / "stdout.log"
    saved = {p: (p.read_bytes() if p.exists() else None) for p in protected_files}
    run_env = os.environ.copy()
    run_env.update(env)
    run_env["REPO_ROOT"] = str(REPO_ROOT)
    run_env.setdefault("PYTHONUNBUFFERED", "1")
    with _PERFORMANCE_RUN_LOCK:
        if job.get("state") == "failed":
            return
        with _PERFORMANCE_JOB_LOCK:
            job["state"] = "running"
            job["started_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
            _write_job_metadata(job)
        try:
            with open(stdout_log, "w", encoding="utf-8", errors="replace") as out:
                out.write("Command: " + " ".join(cmd) + "\n\n")
                out.flush()
                proc = subprocess.Popen(
                    cmd,
                    cwd=str(cwd),
                    env=run_env,
                    stdout=out,
                    stderr=subprocess.STDOUT,
                    text=True,
                )
                job["process"] = proc
                rc = proc.wait()
            with _PERFORMANCE_JOB_LOCK:
                job["exit_code"] = rc
                job["state"] = "finished" if rc == 0 else "failed"
            if job.get("kind") == "run_all":
                _copy_performance_run_all_results(job)
            for src, name in result_files:
                _copy_if_exists(src, hist / name)
        except Exception as exc:
            with _PERFORMANCE_JOB_LOCK:
                job["state"] = "failed"
                job["error"] = str(exc)
            with open(stdout_log, "a", encoding="utf-8", errors="replace") as out:
                out.write(f"\n[performance-dashboard] job failed: {exc}\n")
        finally:
            _restore_baseline(saved)
            with _PERFORMANCE_JOB_LOCK:
                job["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
                _write_job_metadata(job)


@app.route("/api/performance/run_one", methods=["POST"])
def performance_run_one():
    body = request.get_json(force=True) or {}
    module = str(body.get("module", ""))
    pf_id = str(body.get("fn_id", ""))
    try:
        pf_dir = _safe_pf_dir(module, pf_id)
        env = _sanitize_performance_env(body.get("env", {}))
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    with _PERFORMANCE_JOB_LOCK:
        if _active_performance_job_exists():
            return jsonify({"ok": False, "error": "已有性能验收任务正在执行"}), 409
        job = _prepare_performance_job("run_one", env, module, pf_id)
    hist = Path(job["history_abs"])
    run_env = dict(env)
    run_env["OUT_DIR"] = str(hist)
    cmd = ["bash", str(pf_dir / "run.sh")]
    protected = [pf_dir / "summary.md", pf_dir / "raw.json"]
    results = [(hist / "summary.md", "summary.md"), (hist / "raw.json", "raw.json"), (hist / "logs" / "run.log", "run.log")]
    th = threading.Thread(
        target=_run_performance_job,
        args=(job["job_id"], cmd, pf_dir, run_env, protected, results),
        daemon=True,
    )
    job["thread"] = th
    th.start()
    return jsonify({"ok": True, "job_id": job["job_id"], "history_dir": job["history_dir"]})


@app.route("/api/performance/run_all", methods=["POST"])
def performance_run_all():
    body = request.get_json(force=True) or {}
    env = _sanitize_performance_env(body.get("env", {}))
    with _PERFORMANCE_JOB_LOCK:
        if _active_performance_job_exists():
            return jsonify({"ok": False, "error": "已有性能验收任务正在执行"}), 409
        job = _prepare_performance_job("run_all", env)
    cmd = ["bash", str(PERFORMANCES_DIR / "run_all.sh")]
    protected = [PERFORMANCES_DIR / "summary.md"]
    for pf_id, _ in _PERFORMANCE_MODULES["performance"]["functions"]:
        protected.extend([
            PERFORMANCES_DIR / pf_id / "summary.md",
            PERFORMANCES_DIR / pf_id / "raw.json",
            PERFORMANCES_DIR / pf_id / "run_all.last.log",
        ])
    results = [(PERFORMANCES_DIR / "summary.md", "summary.md")]
    th = threading.Thread(
        target=_run_performance_job,
        args=(job["job_id"], cmd, PERFORMANCES_DIR, env, protected, results),
        daemon=True,
    )
    job["thread"] = th
    th.start()
    return jsonify({"ok": True, "job_id": job["job_id"], "history_dir": job["history_dir"]})


@app.route("/api/performance/jobs/<job_id>")
def performance_job(job_id):
    job = _PERFORMANCE_JOBS.get(job_id)
    if not job:
        job = _recover_performance_job(job_id)
    if not job:
        return jsonify({"ok": False, "error": "任务不存在"}), 404
    stdout_log = Path(job["history_abs"]) / "stdout.log"
    stdout_tail = ""
    if stdout_log.exists():
        size = stdout_log.stat().st_size
        with open(stdout_log, "rb") as f:
            if size > 65536:
                f.seek(size - 65536)
            stdout_tail = f.read().decode("utf-8", errors="replace")
    out = {
        k: v for k, v in job.items()
        if k not in {"thread", "process", "history_abs"}
    }
    out["stdout_tail"] = stdout_tail
    return jsonify(out)


# Must be declared before the dashboard catch-all route below.
@app.route("/function-dashboard/")
def function_dashboard_index():
    return send_from_directory(FUNCTION_DASH_DIR, "index.html")


@app.route("/function-dashboard/<path:p>")
def function_dashboard_asset(p):
    return send_from_directory(FUNCTION_DASH_DIR, p)


@app.route("/performance-dashboard/")
def performance_dashboard_index():
    return send_from_directory(PERFORMANCE_DASH_DIR, "index.html")


@app.route("/performance-dashboard/<path:p>")
def performance_dashboard_asset(p):
    return send_from_directory(PERFORMANCE_DASH_DIR, p)


# ---------- Dashboard static serving ----------
@app.route("/")
def index():
    return send_from_directory(DASH_DIR, "index.html")

@app.route("/<path:p>")
def dashboard_asset(p):
    return send_from_directory(DASH_DIR, p)

if __name__ == "__main__":
    _dash_abs = os.path.abspath(DASH_DIR)
    _has_new  = os.path.exists(os.path.join(_dash_abs, "m5_perf.js"))
    print(f"[control_plane] starting on :{CTRL_PORT}  role={ROLE}  uds={UDS_PATH}")
    print(f"[control_plane] DASH_DIR = {_dash_abs}  "
          f"(new-dashboard={'YES' if _has_new else 'NO — 旧面板或路径错误'})")
    app.run(host="0.0.0.0", port=CTRL_PORT, threaded=True)
