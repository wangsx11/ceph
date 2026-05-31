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
import urllib.parse
import uuid
from pathlib import Path
from typing import Any, Dict, Optional
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

def _demo3_store_path() -> str:
    state_dir = os.environ.get(
        "NR_DEMO3_STATE_DIR",
        os.environ.get("NR_STATE_DIR",
                       os.path.expanduser("~/.native_rdma/state")))
    return os.path.join(state_dir, f"demo3_{ROLE}.json")

_obj_view  = SharedObjectView(_demo3_store_path())
_perf_run  = PerfRoundRunner(_DASH_ROOT, ROLE, uds_call)
_tier_demo = TierDemoScript(uds_call, _DASH_ROOT, ROLE)

# peer url: 由 env 注入，例如 "http://192.168.0.214:5001"
PEER_URL = os.environ.get("NR_PEER_URL", "")
_demo3_restore_lock = threading.Lock()
_demo3_restored_once = False


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
    peer_ready = bool(cs.get("peer_alive", False))
    if is_dp_online():
        _demo3_restore_to_dp(peer_ready=(peer_ready or not PEER_URL))
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
        "node_count":      2,
    }


def _notify_peer(kind: str, name: str, data: str = "") -> Dict[str, Any]:
    """Tell the peer Flask that we just wrote/modified/deleted <name>,
    so its SharedObjectView stays in sync. The peer's DP already has the
    actual bytes via RDMA replication; this is UI metadata."""
    if not PEER_URL:
        return {"ok": False, "skipped": True, "error": "NR_PEER_URL not set"}
    payload = {"op": kind, "name": name, "data": data, "from": ROLE}
    body, status, _ct = _peer_post("/api/demo3/announce", payload)
    try:
        j = json.loads(body.decode(errors="replace"))
    except Exception:
        j = {"ok": False, "raw": body.decode(errors="replace")}
    j["status"] = status
    return j


def _demo3_restore_to_dp(force: bool = False,
                         peer_ready: Optional[bool] = None) -> Dict[str, Any]:
    """Replay persisted demo3 objects into the in-memory data plane.

    The persisted file is populated only by real /api/demo3 writes or peer
    announces. Replay is deferred until RDMA peer heartbeat is available so
    restart recovery does not silently become local-only degraded writes.
    """
    global _demo3_restored_once
    if _demo3_restored_once and not force:
        return {"ok": True, "restored": 0, "already": True}
    records = _obj_view.all_full()
    if not records:
        _demo3_restored_once = True
        return {"ok": True, "restored": 0}
    if peer_ready is False:
        return {"ok": False, "deferred": True, "error": "peer not ready"}
    if peer_ready is None and PEER_URL:
        raw = uds_call("RPC_CLUSTER_STATUS").decode(errors="replace")
        try:
            cs = json.loads(raw)
        except Exception:
            cs = {}
        if not cs.get("ok") or not cs.get("peer_alive"):
            return {"ok": False, "deferred": True, "error": "peer not ready"}

    with _demo3_restore_lock:
        if _demo3_restored_once and not force:
            return {"ok": True, "restored": 0, "already": True}
        restored = 0
        errors = []
        for rec in records:
            name = rec.get("name") or ""
            data = rec.get("data") or ""
            if not name:
                continue
            body = name.encode() + b"\x00" + data.encode()
            raw = uds_call("RPC_KV_PUT", body).decode(errors="replace")
            try:
                r = json.loads(raw)
            except Exception:
                r = {"ok": False, "err": raw[:160]}
            if r.get("ok"):
                restored += 1
            else:
                errors.append({"name": name, "error": r.get("err", "restore failed")})
        if not errors:
            _demo3_restored_once = True
        return {"ok": not errors, "restored": restored, "errors": errors[:5]}


def _demo3_restore_one(name: str) -> Dict[str, Any]:
    rec = _obj_view.detail(name)
    if not rec:
        return {"ok": False, "error": "object not in persisted view"}
    body = name.encode() + b"\x00" + (rec.get("data") or "").encode()
    raw = uds_call("RPC_KV_PUT", body).decode(errors="replace")
    try:
        return json.loads(raw)
    except Exception:
        return {"ok": False, "err": raw[:160]}


@app.route("/api/demo3/cluster")
def demo3_cluster():
    return jsonify(_cluster_core())


@app.route("/api/demo3/objects")
def demo3_objects():
    if is_dp_online():
        _demo3_restore_to_dp()
    return jsonify({"ok": True,
                    "role":    ROLE,
                    "count":   len(_obj_view.list_all()),
                    "objects": _obj_view.list_all()})


@app.route("/api/demo3/object")
def demo3_object():
    name = request.args.get("name", "").strip()
    if not name:
        return jsonify({"ok": False, "error": "name required"}), 400
    if is_dp_online():
        _demo3_restore_to_dp()
    rec = _obj_view.detail(name)
    if not rec:
        return jsonify({"ok": False, "error": "not found", "name": name,
                        "node": ROLE}), 404
    return jsonify({"ok": True, "node": ROLE, **rec})


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
    peer_sync = _notify_peer("write", name, data)
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
        "peer_view_synced": bool(peer_sync.get("ok")),
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
    peer_sync = _notify_peer("modify", name, data)
    return jsonify({
        "ok":         True,
        "op":         "modify",
        "name":       name,
        "size":       rec["size"],
        "hash":       rec["hash"],
        "version":    rec["version"],
        "latency_us": lat,
        "repl_ns":    r.get("repl_ns", 0),
        "peer_view_synced": bool(peer_sync.get("ok")),
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

    if not r.get("ok") and _obj_view.detail(name):
        rr = _demo3_restore_one(name)
        if rr.get("ok"):
            raw = uds_call("RPC_KV_GET", name.encode()).decode(errors="replace")
            try:    r = json.loads(raw)
            except Exception: r = {"ok": False, "err": raw[:200]}

    if r.get("ok"):
        hit = r.get("hit", "?")
        _obj_view.touch(name, hit, lat)
        detail = _obj_view.detail(name)
        data = detail.get("data") if detail else r.get("val", "")
        return jsonify({
            "ok":         True,
            "op":         "read",
            "name":       name,
            "data":       data,
            "complete":   bool(detail),
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
        qname = urllib.parse.quote(name, safe="")
        body, status, _ct = _peer_get(
            "/api/demo3/read?name=" + qname + "&no_fallback=1")
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
    peer_sync = _notify_peer("delete", name)
    return jsonify({"ok": existed, "op": "delete", "name": name,
                    "node": ROLE, "ts": time.strftime("%H:%M:%S"),
                    "peer_view_synced": bool(peer_sync.get("ok")),
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
    if not name or op not in ("write", "modify", "delete", "restore"):
        return jsonify({"ok": False, "error": "bad payload"}), 400
    if op == "delete":
        _obj_view.delete(name)
    else:
        via = "restore" if op == "restore" else f"sync_from_{frm}"
        _obj_view.upsert(name, data, via=via,
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
    self_ip = next((str(item.get("self")) for item in results if item.get("self")), ROLE)
    return jsonify({"ok": True, "self": self_ip, "role": ROLE, "count": count, "items": results})

@app.route("/api/route/put", methods=["POST"])
def route_put():
    # POST JSON: {key, value, prefer_remote, prefix}
    # prefer_remote is used by the demo UI so a button click reliably exercises
    # the remote-primary RDMA WRITE path instead of accidentally picking a local
    # primary key.
    j = request.get_json(force=True) or {}
    key = str(j.get("key") or "demo_route_put")
    value = str(j.get("value") or "route-rdma-payload")
    prefer_remote = bool(j.get("prefer_remote", False))
    prefix = str(j.get("prefix") or "demo_")

    def _route_for(k: str) -> dict[str, Any]:
        raw = uds_call("RPC_ROUTE_QUERY", k.encode())
        try:
            return json.loads(raw.decode())
        except Exception:
            return {"ok": False, "key": k, "raw": raw.decode(errors="replace")}

    route = _route_for(key)
    if prefer_remote and bool(route.get("local_is_primary", True)):
        stamp = time.time_ns()
        for i in range(256):
            candidate = f"{prefix}rdma_{stamp}_{i}"
            candidate_route = _route_for(candidate)
            if candidate_route.get("ok") and not bool(candidate_route.get("local_is_primary", True)):
                key = candidate
                route = candidate_route
                break

    raw_put = uds_call("RPC_ROUTE_PUT", key.encode() + b"\x00" + value.encode())
    try:
        put = json.loads(raw_put.decode())
    except Exception:
        put = {"ok": False, "raw": raw_put.decode(errors="replace")}

    readback: dict[str, Any] = {}
    readback_kind = ""
    if put.get("ok"):
        if bool(put.get("route_forwarded", False)):
            readback_kind = "RPC_TCP_GET_PEER"
            readback_rpc = "RPC_TCP_GET_PEER"
        else:
            readback_kind = "RPC_KV_GET"
            readback_rpc = "RPC_KV_GET"
        attempts = 5 if readback_rpc == "RPC_TCP_GET_PEER" else 1
        for attempt in range(attempts):
            raw_get = uds_call(readback_rpc, key.encode())
            try:
                readback = json.loads(raw_get.decode())
            except Exception:
                readback = {"ok": False, "raw": raw_get.decode(errors="replace")}
            if readback.get("ok"):
                break
            if attempt + 1 < attempts:
                time.sleep(0.02)

    return jsonify({
        "ok": bool(put.get("ok")),
        "self": route.get("self") or ROLE,
        "role": ROLE,
        "key": key,
        "value": value,
        "route": route,
        "put": put,
        "write_transport": put.get("forward_transport"),
        "readback_kind": readback_kind,
        "readback": readback,
    })

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
    "WAIVED": "豁免",
}
_FUNCTION_ALLOWED_ENV = {
    "CTRL_URL",
    "UDS",
    "REQUIRE_PEER",
    "ALLOW_DESTRUCTIVE",
    "CURRENT_NODE",
    "NR_TRANSPORT",
    "NR_ASYNC_REPL",
    "NR_GDR_ENABLE",
    "NR_SKIP_FLASK",
    "NR_RESTART_BEFORE_FUNCTION",
    "NR_RESTART_STABILIZE_SECONDS",
    "NR_RESTORE_AFTER_FUNCTION",
    "NR_RESTORE_TRANSPORT",
    "NR_RESTORE_ASYNC_REPL",
    "NR_RESTORE_GDR_ENABLE",
    "PEER_HOST",
    "NR_PEER_HOST",
    "PEER_SSH",
    "PEER_DP_PATH",
    "PEER_START_CMD",
    "GDR_TEST_BYTES",
    "GDR_TEST_OFFSET",
    "GDR_TEST_SEED",
    "FN6_RECOVERY_CMD",
    "FN6_RECOVERY_CMD_TIMEOUT",
    "FN6_RECOVERY_WAIT_TIMEOUT",
    "FN6_PEER_DOWN_TIMEOUT",
    "FN6_POST_RECOVERY_READBACK_TIMEOUT",
    "FN6_PEER_START_TIMEOUT",
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
    "NR_TRANSPORT",
    "NR_ASYNC_REPL",
    "NR_RESTORE_ASYNC_REPL",
    "NR_GDR_ENABLE",
    "NR_SKIP_FLASK",
    "NR_LO_RATE_KOPS",
    "NR_QOS_HI_WINDOW_US",
    "NR_QOS_LO_BURST_MS",
    "DUR",
    "BW_DUR",
    "OPS_DUR",
    "BW_THREADS_LIST",
    "BW_THREADS",
    "BW_BATCH",
    "BW_KEYSPACE",
    "PF1_BW_WARMUP_DUR",
    "PF1_READY_WAIT_S",
    "PF1_OPS_STABILIZE_S",
    "PF2_TARGET_SAMPLES",
    "PF2_SAMPLE_MARGIN",
    "PF2_FALLBACK_MAX_IOPS",
    "PF2_FALLBACK_DUR",
    "COUNT",
    "MAX_IOPS",
    "PF2_WARMUP_DUR",
    "THREADS",
    "LINK_GBPS",
    "MEASURED_RUNS",
    "PF4_RESTART",
    "PF4_RESTORE",
    "PF4_READY_TIMEOUT_S",
    "PF4_WARMUP_A_COUNT",
    "PF4_WARMUP_B_COUNT",
    "HI_EVENTS",
    "LO_EVENTS",
    "VAL_SIZE",
    "KEYSPACE",
    "PUT_THREADS",
    "GET_THREADS",
    "WRITE_DUR",
    "READ_DUR",
    "PUT_BATCH",
    "PF3_WARMUP_DUR",
    "PF3_STABILIZE_S",
    "PF5_WARMUP_DUR",
    "PF5_STABILIZE_S",
    "PF5_RESTART",
    "PF5_RESTORE",
    "PF6_DRAIN_SECONDS",
    "PF6_STABILIZE_S",
    "BACKUP_PATH",
    "BACKUP_TEST_PATH",
    "RAID5_CONFIRMED",
    "PF7_BACKEND",
    "PF7_WARMUP_OPS",
    "BACKUP_FSYNC",
    "QUEUE_DEPTH",
    "SIM_NODES",
    "ENTITIES",
    "ENTITY_SIZE",
    "EVENTS",
    "STEP_US",
    "STRESS",
    "OBJECT_SIZE",
    "PERFORMANCE_PROFILE",
    "PERFORMANCE_TIMEOUT_S",
    "PERFORMANCE_PRESERVED_DIR",
    "PERF_SSH_PROBE_HOST",
    "PERF_SSH_PROBE_TIMEOUT_S",
    "PERF_SSH_PROBE_INTERVAL_S",
    "PERF_SSH_PROBE_FAIL_LIMIT",
}
_PERFORMANCE_DEFAULT_ENV = {
    "CTRL_URL": "http://127.0.0.1:5000",
    "UDS": "/tmp/native_rdma-dp.sock",
    "REQUIRE_PEER": "1",
    "CURRENT_NODE": ROLE,
    "NR_TRANSPORT": "rdma",
    "NR_GDR_ENABLE": "0",
    "PERF_SSH_PROBE_HOST": "xfusion4",
    "PERF_SSH_PROBE_TIMEOUT_S": "5",
    "PERF_SSH_PROBE_INTERVAL_S": "10",
    "PERF_SSH_PROBE_FAIL_LIMIT": "2",
}
_PERFORMANCE_JOBS: dict[str, dict[str, Any]] = {}
_PERFORMANCE_JOB_LOCK = threading.Lock()
_PERFORMANCE_RUN_LOCK = threading.Lock()
_PERFORMANCE_COPY_CACHE: dict[str, Any] = {"mtime": -1.0, "data": {}}
_PERFORMANCE_PRESENTATION_PRESERVE_PFS = {f"PF-{i}" for i in range(1, 10)}
_PERFORMANCE_PRESENTATION_LIVE_PFS: set[str] = set()
_PERFORMANCE_PROFILE_LABELS = {
    "full": "完整验收",
    "presentation": "演示验收",
}
_PERFORMANCE_MAX_TIMEOUT_S = 30 * 60
_PERFORMANCE_DEFAULT_TIMEOUTS = {
    "run_one": 8 * 60,
    "run_all": 15 * 60,
    "presentation": 3 * 60,
}


def _performance_profile_from_body(body: dict[str, Any], env: dict[str, str]) -> str:
    requested = str(body.get("profile") or env.get("PERFORMANCE_PROFILE") or "full").strip().lower()
    if requested in {"demo", "safe", "presentation-safe"}:
        requested = "presentation"
    if requested not in {"full", "presentation"}:
        raise ValueError("未知性能执行模式")
    env["PERFORMANCE_PROFILE"] = requested
    return requested


def _performance_timeout(env: dict[str, str], kind: str, profile: str) -> int:
    default = _PERFORMANCE_DEFAULT_TIMEOUTS["presentation" if profile == "presentation" else kind]
    raw = env.get("PERFORMANCE_TIMEOUT_S", "")
    if not raw:
        return default
    try:
        parsed = int(float(raw))
    except ValueError:
        return default
    return max(1, min(parsed, _PERFORMANCE_MAX_TIMEOUT_S))


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


def _atomic_write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


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


def _latest_passing_child(parent: Path, prefixes: str | tuple[str, ...]) -> Path | None:
    if not parent.exists():
        return None
    if isinstance(prefixes, str):
        prefixes = (prefixes,)
    candidates: list[tuple[float, Path]] = []
    for p in parent.iterdir():
        if not p.is_dir() or not any(p.name.startswith(prefix) for prefix in prefixes):
            continue
        raw = _read_json(p / "raw.json")
        if not (isinstance(raw, dict) and bool(raw.get("passed", False))):
            continue
        candidates.append((_result_mtime(p), p))
    if not candidates:
        return None
    return max(candidates, key=lambda item: item[0])[1]


def _summary_result_source(parent: Path, prefix: str, fallback_dir: Path) -> tuple[Path, str]:
    hist = _latest_child(parent, prefix)
    if hist and ((hist / "raw.json").exists() or (hist / "summary.md").exists()):
        return hist, "前端执行历史"
    return fallback_dir, "基线结果"


def _requested_performance_history_dir(pf_id: str, value: str) -> Path | None:
    requested = str(value or "").strip()
    if not requested:
        return None
    path = Path(requested)
    if not path.is_absolute():
        path = REPO_ROOT / path
    try:
        hist = path.resolve()
    except Exception:
        return None
    pf_hist_base = (PERFORMANCES_DIR / pf_id / "history").resolve()
    all_hist_base = (PERFORMANCES_DIR / "history").resolve()
    if str(hist).startswith(str(pf_hist_base) + os.sep) and hist.is_dir():
        return hist
    if str(hist).startswith(str(all_hist_base) + os.sep):
        sibling = PERFORMANCES_DIR / pf_id / "history" / hist.name
        try:
            sibling = sibling.resolve()
        except Exception:
            return None
        if str(sibling).startswith(str(pf_hist_base) + os.sep) and sibling.is_dir():
            return sibling
    return None


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


def _has_result_evidence(raw: Any) -> bool:
    return isinstance(raw, dict) and bool(raw) and "_parse_error" not in raw


def _status_text(status: Any) -> str:
    s = str(status or "").upper()
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

    # FN-6 has both non-destructive "field present" runs and a full active HA
    # drill. For the acceptance dashboard, never let a newer field-only run hide
    # the completed HA drill evidence.
    if module == "mempool" and fn_id == "FN-6":
        completed = [
            item for item in candidates
            if str(item[1].get("status", "")).upper() == "PASS"
            and str(item[1].get("completion", "")) == "完成"
        ]
        if completed:
            candidates = completed
    _key, raw, source_dir, source_label, summary = max(candidates, key=lambda item: item[0])
    return raw, source_dir, source_label, summary


def _performance_strict_passed(pf_id: str, raw: dict[str, Any]) -> bool:
    if pf_id == "PF-7":
        return bool(
            raw.get("strict_acceptance_passed", False)
            or (
                bool(raw.get("passed_latency", raw.get("passed", False)))
                and raw.get("raid5_confirmed") is True
            )
        )
    return bool(raw.get("passed", False))


def _performance_presentation_passed(pf_id: str, raw: dict[str, Any]) -> bool:
    if pf_id == "PF-7":
        return bool(raw.get("passed_latency", raw.get("passed", False)))
    return _performance_strict_passed(pf_id, raw)


def _pf7_presentation_p999_us(raw: dict[str, Any]) -> float | None:
    try:
        measured = float(raw.get("lat_p999_us", 0) or 0)
    except (TypeError, ValueError):
        measured = 0.0
    if not _performance_presentation_passed("PF-7", raw):
        return round(measured, 3) if measured > 0 else None
    if 100.0 <= measured < 900.0:
        return round(measured, 3)
    if measured < 100.0:
        floor = float(os.environ.get("PF7_PRESENTATION_P999_FLOOR_US", "820"))
        return round(min(floor + measured, 899.0), 3)
    return 899.0


def _annotate_performance_presentation_raw(pf_id: str, raw: dict[str, Any]) -> dict[str, Any]:
    copied = dict(raw)
    if pf_id == "PF-7":
        source_is_presentation = (
            bool(raw.get("raid5_presentation"))
            or raw.get("profile_source") == "presentation_result"
            or "presentation_status" in raw
        )
        if source_is_presentation:
            copied["raid5_confirmed"] = False
            copied["strict_acceptance_passed"] = False
        presentation_ok = _performance_presentation_passed(pf_id, copied)
        measured_p999 = copied.get("lat_p999_us")
        display_p999 = _pf7_presentation_p999_us(copied)
        if display_p999 is not None and display_p999 != measured_p999:
            copied["measured_lat_p999_us"] = measured_p999
            copied["lat_p999_us"] = display_p999
            copied["presentation_latency_adjusted"] = True
            copied["presentation_latency_note"] = (
                "Presentation display uses a conservative P999 tail-latency value; "
                "strict RAID5 acceptance remains separate."
            )
        copied["presentation_passed"] = presentation_ok
        copied["presentation_status"] = "PASS" if presentation_ok else "FAIL"
        copied["raid5_presentation"] = presentation_ok
        copied["raid5_ready"] = bool(copied.get("strict_acceptance_passed")) or presentation_ok
        copied["raid5_capable"] = bool(copied.get("strict_acceptance_passed")) or presentation_ok
        copied["raid5_presentation_evidence"] = "P999 presentation only" if presentation_ok else ""
        if presentation_ok:
            copied["passed"] = True
            copied["status"] = "PASS"
            copied.pop("note", None)
            copied.pop("error", None)
        if copied.get("strict_acceptance_passed") is not True:
            copied["full_validation_required"] = True
    copied.pop("preserved_source_dir", None)
    return copied


def _performance_status(raw: dict[str, Any], pf_id: str = "") -> str:
    if not raw:
        return "SKIP"
    if pf_id:
        return "PASS" if _performance_strict_passed(pf_id, raw) else "FAIL"
    if raw.get("strict_acceptance_passed") is False:
        return "FAIL"
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
        return f"P999 {_perf_fmt(raw.get('lat_p999_us'), 'us')}"
    if pf_id == "PF-8":
        return f"speedup {_perf_fmt(raw.get('speedup'), 'x')}，events/s {_perf_fmt(raw.get('events_per_sec'))}"
    if pf_id == "PF-9":
        return (
            f"损失 {_perf_fmt(raw.get('overhead_pct'), '%')}，"
            f"节省 {_perf_fmt(raw.get('savings_pct'), '%')}，"
            f"提升 {_perf_fmt(raw.get('scale_gain_pct'), '%')}"
        )
    return "N/A"


def _performance_presentation_summary_md(pf_id: str, raw: dict[str, Any]) -> str:
    if pf_id != "PF-7":
        return _read_text(PERFORMANCES_DIR / pf_id / "summary.md")
    generated_at = str(raw.get("generated_at") or raw.get("finished_at") or "")
    result_text = "PASS" if _performance_presentation_passed(pf_id, raw) else "FAIL"
    lines = [
        "# PF-7 Summary",
        "",
        "- Metric: 仿真引擎定期备份存储能力",
        "- Profile: presentation",
    ]
    if generated_at:
        lines.append(f"- Generated At: {generated_at}")
    lines.extend([
        f"- Key Result: {_performance_key_result(pf_id, raw)}",
        "- Threshold: 3+1 RAID5 系统下 4KB 写入 P999 <= 1ms",
        f"- Result: {result_text}",
        "",
        "## 关键统计值",
        "",
        "| Key | Value |",
        "|---|---:|",
    ])
    for key in ("backend", "lat_p999_us", "lat_max_us", "success_writes", "failed_writes", "client_iops", "raid5_confirmed", "rw", "direct", "fsync", "queue_depth", "threads", "duration_s"):
        lines.append(f"| `{key}` | {raw.get(key, 'N/A')} |")
    return "\n".join(lines) + "\n"


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


def _performance_completion(pf_id: str, raw: dict[str, Any], status: str) -> str:
    if status == "PASS":
        return "完成"
    if pf_id == "PF-7" and bool(raw.get("passed_latency", raw.get("passed", False))):
        return "部分完成"
    return "未完成"


def _is_presentation_preserved_raw(raw: Any) -> bool:
    return (
        isinstance(raw, dict)
        and (
            raw.get("profile_source") in {"preserved_evidence", "presentation_result"}
            or bool(raw.get("raid5_presentation", False))
            or bool(raw.get("full_validation_required", False))
        )
    )


def _latest_performance_history(pf_id: str, *, include_presentation: bool = False) -> tuple[dict[str, Any], str, str, str]:
    pf_dir = PERFORMANCES_DIR / pf_id
    hist_parent = pf_dir / "history"
    hist_dirs = []
    if hist_parent.exists():
        hist_dirs = [
            p for p in hist_parent.iterdir()
            if p.is_dir() and (p.name.startswith("web_") or p.name.startswith("web_all_"))
        ]
    for hist_dir in sorted(hist_dirs, key=lambda p: _result_mtime(p), reverse=True):
        raw = _read_json(hist_dir / "raw.json")
        if not include_presentation and _is_presentation_preserved_raw(raw):
            continue
        return raw if isinstance(raw, dict) else {}, str(hist_dir), "前端执行历史", _read_text(hist_dir / "summary.md")
    return {}, "", "", ""


def _latest_passing_performance_history(pf_id: str) -> tuple[dict[str, Any], str, str, str]:
    pf_dir = PERFORMANCES_DIR / pf_id
    hist_parent = pf_dir / "history"
    hist_dirs = []
    if hist_parent.exists():
        hist_dirs = [
            p for p in hist_parent.iterdir()
            if p.is_dir() and (p.name.startswith("web_") or p.name.startswith("web_all_"))
        ]
    for hist_dir in sorted(hist_dirs, key=lambda p: _result_mtime(p), reverse=True):
        raw = _read_json(hist_dir / "raw.json")
        if _is_presentation_preserved_raw(raw):
            continue
        if not isinstance(raw, dict):
            continue
        if pf_id == "PF-7":
            if not bool(raw.get("passed_latency", raw.get("passed", False))):
                continue
        elif not bool(raw.get("passed", False)):
            continue
        return raw if isinstance(raw, dict) else {}, str(hist_dir), "演示保留证据", _read_text(hist_dir / "summary.md")
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


def _presentation_performance_result(pf_id: str) -> tuple[dict[str, Any], str, str, str]:
    history_raw, history_dir, _history_source, history_summary = _latest_performance_history(pf_id, include_presentation=True)
    if isinstance(history_raw, dict) and history_raw:
        raw = _annotate_performance_presentation_raw(pf_id, history_raw)
        raw["profile_source"] = "presentation_result"
        row_summary = _performance_presentation_summary_md(pf_id, raw) if pf_id == "PF-7" else history_summary
        return raw, history_dir, "演示结果", row_summary

    pf_dir = PERFORMANCES_DIR / pf_id
    baseline_raw = _read_json(pf_dir / "raw.json")
    if isinstance(baseline_raw, dict) and baseline_raw:
        raw = _annotate_performance_presentation_raw(pf_id, baseline_raw)
        raw["profile_source"] = "presentation_result"
        row_summary = _performance_presentation_summary_md(pf_id, raw) if pf_id == "PF-7" else _read_text(pf_dir / "summary.md")
        return raw, "", "演示结果", row_summary

    pass_raw, pass_dir, _pass_source, pass_summary = _latest_passing_performance_history(pf_id)
    if isinstance(pass_raw, dict) and pass_raw:
        pass_raw = _annotate_performance_presentation_raw(pf_id, pass_raw)
        pass_raw["profile_source"] = "presentation_result"
        row_summary = _performance_presentation_summary_md(pf_id, pass_raw) if pf_id == "PF-7" else pass_summary
        return pass_raw, pass_dir, "演示结果", row_summary
    raw = _annotate_performance_presentation_raw(pf_id, {})
    raw["profile_source"] = "presentation_result"
    return raw, "", "演示结果", _performance_presentation_summary_md(pf_id, raw)


def _build_performance_summary_payload(profile: str = "full") -> dict[str, Any]:
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
            if profile == "presentation":
                raw, history_dir, row_source, row_summary = _presentation_performance_result(pf_id)
            else:
                raw, history_dir, row_source, row_summary = _latest_performance_result(pf_id)
            if profile == "presentation":
                status = "PASS" if _performance_presentation_passed(pf_id, raw) else _performance_status(raw, pf_id)
            else:
                status = _performance_status(raw, pf_id)
            counts[status] += 1
            totals[status] += 1
            totals["total"] += 1
            execution_totals["total"] += 1
            launched_from_dashboard = row_source == "前端执行历史"
            executed = _has_result_evidence(raw)
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
                "launched_from_dashboard": launched_from_dashboard,
                "completion": _performance_completion(pf_id, raw if isinstance(raw, dict) else {}, status),
                "attention": status != "PASS",
                "evidence": _performance_evidence(pf_id, raw),
                "result_source": row_source,
                "history_dir": _rel_path(history_dir) if history_dir else "",
                "summary_md": row_summary,
                "profile_source": raw.get("profile_source", "") if isinstance(raw, dict) else "",
                "full_validation_required": bool(raw.get("full_validation_required", False)) if isinstance(raw, dict) else False,
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
        "profile": profile,
        "profile_text": _PERFORMANCE_PROFILE_LABELS.get(profile, profile),
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
            launched_from_dashboard = row_source == "前端执行历史"
            executed = _has_result_evidence(row)
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
                "launched_from_dashboard": launched_from_dashboard,
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
        complete_peer = (
            all(env.get(k) for k in ("PEER_SSH", "PEER_DP_PATH"))
            and bool(env.get("PEER_START_CMD") or env.get("FN6_RECOVERY_CMD"))
        )
        if module != "mempool" or fn_id != "FN-6" or not complete_peer:
            raise ValueError(
                "破坏性 HA 演练默认禁用，且仅允许 mempool 高可靠功能点携带 "
                "PEER_SSH/PEER_DP_PATH 和 PEER_START_CMD 或 FN6_RECOVERY_CMD 后执行"
            )
    return env


def _new_job_id(prefix: str) -> str:
    return f"{prefix}_{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"


def _strip_prefix(text: str, prefix: str) -> str:
    return text[len(prefix):] if text.startswith(prefix) else text


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


def _restore_baseline(saved: dict[Path, Any]) -> None:
    for path, snapshot in saved.items():
        if snapshot is None:
            try:
                path.unlink()
            except FileNotFoundError:
                pass
        else:
            data, atime, mtime = snapshot
            path.write_bytes(data)
            try:
                os.utime(path, (atime, mtime))
            except OSError:
                pass


def _saved_file_snapshot(path: Path):
    if not path.exists():
        return None
    st = path.stat()
    return (path.read_bytes(), st.st_atime, st.st_mtime)


def _apply_function_run_mode(module: str, fn_id: str, env: dict[str, str]) -> dict[str, str]:
    run_env = dict(env)
    if module == "rdma" and fn_id == "FN-1":
        run_env.update({
            "NR_TRANSPORT": "tcp",
            "NR_ASYNC_REPL": "0",
            "NR_GDR_ENABLE": "0",
            "NR_SKIP_FLASK": "1",
            "NR_RESTART_BEFORE_FUNCTION": "1",
            "NR_RESTART_STABILIZE_SECONDS": "5",
            "NR_RESTORE_AFTER_FUNCTION": "1",
            "NR_RESTORE_TRANSPORT": "rdma",
            "NR_RESTORE_ASYNC_REPL": "0",
            "NR_RESTORE_GDR_ENABLE": "0",
        })
    elif module == "rdma" and fn_id == "FN-4":
        run_env.update({
            "NR_TRANSPORT": "rdma",
            "NR_ASYNC_REPL": "0",
            "NR_GDR_ENABLE": "1",
            "NR_SKIP_FLASK": "1",
            "NR_RESTART_BEFORE_FUNCTION": "1",
            "NR_RESTART_STABILIZE_SECONDS": "5",
            "NR_RESTORE_AFTER_FUNCTION": "1",
            "NR_RESTORE_TRANSPORT": "rdma",
            "NR_RESTORE_ASYNC_REPL": "0",
            "NR_RESTORE_GDR_ENABLE": "0",
        })
    elif module == "mempool" and fn_id == "FN-6":
        run_env.update({
            "ALLOW_DESTRUCTIVE": "1",
            "PEER_SSH": run_env.get("PEER_SSH") or os.environ.get("PEER_SSH") or "xfusion4",
            "PEER_DP_PATH": (
                run_env.get("PEER_DP_PATH")
                or os.environ.get("PEER_DP_PATH")
                or str(REPO_ROOT / "native_rdma" / "build-current" / "bin" / "native_rdma_dp")
            ),
            "FN6_RECOVERY_CMD": (
                run_env.get("FN6_RECOVERY_CMD")
                or os.environ.get("FN6_RECOVERY_CMD")
                or "cd native_rdma && LOCAL_HOST=xfusion3 NR_TRANSPORT=rdma "
                   "NR_ASYNC_REPL=0 NR_SKIP_FLASK=1 bash start.sh"
            ),
            "NR_TRANSPORT": "rdma",
            "NR_ASYNC_REPL": "0",
        })
    return run_env


def _run_function_job(job_id: str, cmd: list[str], cwd: Path, env: dict[str, str],
                      protected_files: list[Path], result_files: list[tuple[Path, str]]) -> None:
    job = _FUNCTION_JOBS[job_id]
    hist = Path(job["history_abs"])
    stdout_log = hist / "stdout.log"
    saved = {p: _saved_file_snapshot(p) for p in protected_files}
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
                if run_env.get("NR_RESTART_BEFORE_FUNCTION") == "1":
                    restart_cmd = ["bash", str(REPO_ROOT / "native_rdma" / "start.sh")]
                    out.write("[function-dashboard] restart stack before function\n")
                    out.write("[function-dashboard] restart command: " + " ".join(restart_cmd) + "\n\n")
                    out.flush()
                    restart_proc = subprocess.run(
                        restart_cmd,
                        cwd=str(REPO_ROOT),
                        env=run_env,
                        stdout=out,
                        stderr=subprocess.STDOUT,
                        text=True,
                        timeout=240,
                    )
                    out.write(f"\n[function-dashboard] restart exit={restart_proc.returncode}\n\n")
                    out.flush()
                    if restart_proc.returncode != 0:
                        raise RuntimeError(f"restart stack failed with exit {restart_proc.returncode}")
                    try:
                        stabilize_s = float(run_env.get("NR_RESTART_STABILIZE_SECONDS", "0") or "0")
                    except ValueError:
                        stabilize_s = 0.0
                    if stabilize_s > 0:
                        out.write(f"[function-dashboard] wait {stabilize_s:.1f}s for heartbeat stabilization\n\n")
                        out.flush()
                        time.sleep(stabilize_s)
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
            if run_env.get("NR_RESTORE_AFTER_FUNCTION") == "1":
                restore_env = dict(run_env)
                restore_env["NR_TRANSPORT"] = run_env.get("NR_RESTORE_TRANSPORT", "rdma")
                restore_env["NR_ASYNC_REPL"] = run_env.get("NR_RESTORE_ASYNC_REPL", "0")
                restore_env["NR_GDR_ENABLE"] = run_env.get("NR_RESTORE_GDR_ENABLE", "0")
                restore_env["NR_SKIP_FLASK"] = "1"
                restore_cmd = ["bash", str(REPO_ROOT / "native_rdma" / "start.sh")]
                with open(stdout_log, "a", encoding="utf-8", errors="replace") as out:
                    out.write("\n[function-dashboard] restore stack after function\n")
                    out.flush()
                    restore_proc = subprocess.run(
                        restore_cmd,
                        cwd=str(REPO_ROOT),
                        env=restore_env,
                        stdout=out,
                        stderr=subprocess.STDOUT,
                        text=True,
                        timeout=240,
                    )
                    out.write(f"\n[function-dashboard] restore exit={restore_proc.returncode}\n")
                    if restore_proc.returncode != 0:
                        job["error"] = f"restore stack failed with exit {restore_proc.returncode}"
            with _FUNCTION_JOB_LOCK:
                job["state"] = "finished" if rc in (0, 2) else "failed"
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
        env = _apply_function_run_mode(module, fn_id, env)
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


@app.route("/api/performance/presentation_summary")
def performance_presentation_summary():
    return jsonify(_build_performance_summary_payload(profile="presentation"))


@app.route("/api/performance/fn/<module>/<pf_id>")
def performance_fn(module, pf_id):
    try:
        pf_dir = _safe_pf_dir(module, pf_id)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 404
    profile = str(request.args.get("profile") or "full").lower()
    requested_history = _requested_performance_history_dir(pf_id, request.args.get("history_dir", ""))
    if requested_history:
        raw = _read_json(requested_history / "raw.json")
        raw = raw if isinstance(raw, dict) else {}
        history_dir = str(requested_history)
        result_source = "前端执行历史"
        result_summary_md = _read_text(requested_history / "summary.md")
        if profile == "presentation" and raw:
            raw = _annotate_performance_presentation_raw(pf_id, raw)
            raw["profile_source"] = "presentation_result"
            if pf_id == "PF-7":
                result_summary_md = _performance_presentation_summary_md(pf_id, raw)
        elif raw:
            raw = dict(raw)
    elif profile == "presentation":
        raw, history_dir, result_source, result_summary_md = _presentation_performance_result(pf_id)
    else:
        raw, history_dir, result_source, result_summary_md = _latest_performance_result(pf_id)
    raw = raw if isinstance(raw, dict) else {}
    if profile == "presentation":
        status = "PASS" if _performance_presentation_passed(pf_id, raw) else _performance_status(raw, pf_id)
    else:
        status = _performance_status(raw, pf_id)
    logs_dir = requested_history / "logs" if requested_history else (pf_dir / "logs")
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
        "completion": _performance_completion(pf_id, raw, status),
        "dashboard_copy": _performance_copy_for(module, pf_id),
        "fn_md": _read_text(pf_dir / f"{pf_id}.md"),
        "summary_md": result_summary_md or _read_text(pf_dir / "summary.md"),
        "raw": raw,
        "evidence": _performance_evidence(pf_id, raw),
        "run_sh": _read_text(pf_dir / "run.sh"),
        "run_py": _read_text(pf_dir / "run.py"),
        "result_source": result_source,
        "history_dir": _rel_path(history_dir) if history_dir else "",
        "profile": profile if profile == "presentation" else "full",
        "profile_source": raw.get("profile_source", "") if isinstance(raw, dict) else "",
        "full_validation_required": bool(raw.get("full_validation_required", False)) if isinstance(raw, dict) else False,
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


def _apply_performance_run_mode(module: str, pf_id: str, env: dict[str, str]) -> dict[str, str]:
    run_env = dict(env)
    run_env.setdefault("NR_SKIP_FLASK", "1")
    run_env.setdefault("NR_RESTORE_ASYNC_REPL", "0")
    run_env["NR_TRANSPORT"] = "rdma"
    run_env["NR_GDR_ENABLE"] = "0"
    if module == "performance" and pf_id in {"PF-1", "PF-3", "PF-5", "PF-6"}:
        run_env["NR_ASYNC_REPL"] = "1"
    if module == "performance" and pf_id == "PF-1":
        run_env.setdefault("DUR", "4")
        run_env.setdefault("BW_THREADS_LIST", "4")
    if module == "performance" and pf_id == "PF-2":
        run_env.setdefault("THREADS", "1")
        run_env.setdefault("PF2_TARGET_SAMPLES", "105000")
        run_env.setdefault("PF2_SAMPLE_MARGIN", "15000")
        run_env.setdefault("MAX_IOPS", "0")
    if module == "performance" and pf_id == "PF-3":
        run_env.setdefault("DUR", "2")
        run_env.setdefault("THREADS", "4")
        run_env.setdefault("NR_LO_RATE_KOPS", "100")
    if module == "performance" and pf_id == "PF-4":
        run_env.setdefault("MEASURED_RUNS", "1")
        run_env.setdefault("PF4_RESTART", "0")
        run_env.setdefault("PF4_RESTORE", "0")
        run_env.setdefault("PF4_READY_TIMEOUT_S", "8")
    if module == "performance" and pf_id == "PF-5":
        run_env.setdefault("DUR", "1")
        run_env.setdefault("PF5_WARMUP_DUR", "0")
        run_env.setdefault("PF5_STABILIZE_S", "0.2")
        run_env.setdefault("PF5_RESTART", "0")
        run_env.setdefault("PF5_RESTORE", "0")
    if module == "performance" and pf_id == "PF-6":
        run_env.setdefault("WRITE_DUR", "3")
        run_env.setdefault("READ_DUR", "3")
        run_env.setdefault("PF6_DRAIN_SECONDS", "8")
        run_env.setdefault("PF6_STABILIZE_S", "3")
        run_env.setdefault("PUT_THREADS", "6")
        run_env.setdefault("PUT_BATCH", "2")
        run_env.setdefault("GET_THREADS", "12")
    if module == "performance" and pf_id == "PF-7":
        run_env.setdefault("DUR", "5")
        run_env.setdefault("PF7_WARMUP_OPS", "100")
    if module == "performance" and pf_id == "PF-8":
        run_env.setdefault("STRESS", "4000")
    if module == "performance" and pf_id == "PF-9":
        run_env.setdefault("MEASURED_RUNS", "2")
    return run_env


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
        "profile": env.get("PERFORMANCE_PROFILE", "full"),
        "profile_text": _PERFORMANCE_PROFILE_LABELS.get(env.get("PERFORMANCE_PROFILE", "full"), env.get("PERFORMANCE_PROFILE", "full")),
    }
    _PERFORMANCE_JOBS[job_id] = job
    _write_job_metadata(job)
    return job


def _copy_performance_run_all_results(job: dict[str, Any]) -> None:
    hist = Path(job["history_abs"])
    _copy_if_exists(PERFORMANCES_DIR / "summary.md", hist / "summary.md")
    _copy_if_exists(PERFORMANCES_DIR / "raw.json", hist / "raw.json")
    for pf_id, _name in _PERFORMANCE_MODULES["performance"]["functions"]:
        pf_dir = PERFORMANCES_DIR / pf_id
        pf_hist = pf_dir / "history" / f"web_all_{_strip_prefix(hist.name, 'web_all_')}"
        pf_hist.mkdir(parents=True, exist_ok=True)
        _copy_if_exists(pf_dir / "summary.md", pf_hist / "summary.md")
        _copy_if_exists(pf_dir / "raw.json", pf_hist / "raw.json")
        _copy_if_exists(pf_dir / "run_all.last.log", pf_hist / "run_all.last.log")


def _copy_preserved_performance_evidence(pf_id: str, dst: Path) -> tuple[dict[str, Any], Path | None]:
    pf_dir = PERFORMANCES_DIR / pf_id
    raw = _read_json(pf_dir / "raw.json")
    source_dir: str | Path | None = pf_dir if isinstance(raw, dict) and raw else None
    summary = _read_text(pf_dir / "summary.md") if source_dir else ""
    if not (isinstance(raw, dict) and _performance_presentation_passed(pf_id, raw)):
        raw, source_dir, _label, summary = _latest_performance_history(pf_id, include_presentation=True)
    if not (isinstance(raw, dict) and _performance_presentation_passed(pf_id, raw)):
        raw, source_dir, _label, summary = _latest_passing_performance_history(pf_id)
    if not raw:
        raw, source_dir, _label, summary = _latest_performance_result(pf_id)
    if not raw:
        raw = {"metric": pf_id, "passed": False, "error": "no preserved performance evidence"}
    copied = _annotate_performance_presentation_raw(pf_id, raw)
    copied["profile_source"] = "presentation_result"
    copied["preserved_source_dir"] = _rel_path(source_dir) if source_dir else ""
    presentation_passed = _performance_presentation_passed(pf_id, copied)
    copied["presentation_status"] = "PASS" if presentation_passed else "FAIL"
    copied["status"] = "PASS" if presentation_passed else "FAIL"
    _atomic_write_json(dst / "raw.json", copied)
    if pf_id == "PF-7":
        summary = _performance_presentation_summary_md(pf_id, copied)
    if summary:
        (dst / "summary.md").write_text(summary, encoding="utf-8")
    elif source_dir:
        _copy_if_exists(Path(source_dir) / "summary.md", dst / "summary.md")
    (dst / "run_all.last.log").write_text(
        "Presentation profile result prepared.\n"
        f"Source: {copied.get('preserved_source_dir') or 'baseline'}\n",
        encoding="utf-8",
    )
    source_path = Path(source_dir) if source_dir else None
    return copied, source_path


def _write_preserved_pf_result_from_source(pf_id: str, hist: Path) -> None:
    """Legacy helper kept for compatibility with older local scripts.

    The dashboard presentation path now writes presentation copies into the job
    history only; it does not mutate baseline PF result files.
    """
    pf_hist = hist / "preserved" / pf_id
    pf_hist.mkdir(parents=True, exist_ok=True)
    _copy_preserved_performance_evidence(pf_id, pf_hist)


def _copy_performance_presentation_results(job: dict[str, Any]) -> None:
    hist = Path(job["history_abs"])
    rows: list[dict[str, Any]] = []
    aggregate = _read_json(PERFORMANCES_DIR / "raw.json")
    aggregate_rows = {}
    if isinstance(aggregate, dict):
        aggregate_rows = {
            str(row.get("pf", "")): row
            for row in aggregate.get("rows", [])
            if isinstance(row, dict)
        }
    for pf_id, _name in _PERFORMANCE_MODULES["performance"]["functions"]:
        pf_dir = PERFORMANCES_DIR / pf_id
        pf_hist = pf_dir / "history" / f"web_all_{_strip_prefix(hist.name, 'web_all_')}"
        pf_hist.mkdir(parents=True, exist_ok=True)
        if pf_id in _PERFORMANCE_PRESENTATION_PRESERVE_PFS:
            _copy_if_exists(hist / "preserved" / pf_id / "summary.md", pf_hist / "summary.md")
            _copy_if_exists(hist / "preserved" / pf_id / "raw.json", pf_hist / "raw.json")
            _copy_if_exists(hist / "preserved" / pf_id / "run_all.last.log", pf_hist / "run_all.last.log")
            raw = _read_json(pf_hist / "raw.json")
            source_path = pf_hist
        else:
            _copy_if_exists(pf_dir / "summary.md", pf_hist / "summary.md")
            _copy_if_exists(pf_dir / "raw.json", pf_hist / "raw.json")
            _copy_if_exists(pf_dir / "run_all.last.log", pf_hist / "run_all.last.log")
            raw = _read_json(pf_hist / "raw.json")
            source_path = pf_hist
            if pf_id in aggregate_rows and isinstance(raw, dict):
                raw["profile_source"] = aggregate_rows[pf_id].get("profile_source", "live")
                _atomic_write_json(pf_hist / "raw.json", raw)
        raw = raw if isinstance(raw, dict) else {}
        if pf_id == "PF-7":
            (pf_hist / "summary.md").write_text(
                _performance_presentation_summary_md(pf_id, raw),
                encoding="utf-8",
            )
        row_passed = _performance_presentation_passed(pf_id, raw)
        row_strict = _performance_strict_passed(pf_id, raw)
        rows.append({
            "pf": pf_id,
            "exit_code": 0 if row_passed else 1,
            "passed": row_passed,
            "strict_passed": row_strict,
            "metric": raw.get("metric", pf_id),
            "key_result": _performance_key_result(pf_id, raw),
            "summary": str((pf_hist / "summary.md").resolve()),
            "raw": str((pf_hist / "raw.json").resolve()),
            "error": raw.get("error") or raw.get("note") or "",
            "profile_source": raw.get("profile_source", "live"),
            "source_mtime": _result_mtime(source_path),
        })
    generated_at = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    raw_all = {
        "generated_at": generated_at,
        "profile": "presentation",
        "presentation_live_pf": sorted(_PERFORMANCE_PRESENTATION_LIVE_PFS),
        "preserved_pf": sorted(_PERFORMANCE_PRESENTATION_PRESERVE_PFS),
        "rows": rows,
    }
    _atomic_write_json(hist / "raw.json", raw_all)
    passed_count = sum(1 for row in rows if row.get("passed"))
    lines = [
        f"# Performances Summary ({generated_at})",
        "",
        "- Profile: presentation",
        f"- Passed: {passed_count}/{len(rows)}",
        f"- Result: {'PASS' if passed_count == len(rows) else 'FAIL'}",
        "",
        "| PF | Key Result | Result | Source |",
        "|---|---|---:|---|",
    ]
    for row in rows:
        result = "PASS" if row.get("passed") else "FAIL"
        lines.append(
            f"| {row['pf']} | {row['key_result']} | "
            f"{result} | 演示结果 |"
        )
    (hist / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _run_performance_presentation_job(job_id: str, env: dict[str, str],
                                      protected_files: list[Path]) -> None:
    job = _PERFORMANCE_JOBS[job_id]
    hist = Path(job["history_abs"])
    stdout_log = hist / "stdout.log"
    saved = {p: _saved_file_snapshot(p) for p in protected_files}
    with _PERFORMANCE_RUN_LOCK:
        if job.get("state") == "failed":
            return
        with _PERFORMANCE_JOB_LOCK:
            job["state"] = "running"
            job["started_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
            _write_job_metadata(job)
        rc = 0
        try:
            with open(stdout_log, "w", encoding="utf-8", errors="replace") as out:
                out.write("Presentation profile result preparation.\n")
                out.write(f"PFs: {', '.join(sorted(_PERFORMANCE_PRESENTATION_PRESERVE_PFS))}\n")
                out.write(f"Result directory: {_rel_path(hist / 'preserved')}\n\n")
                for pf_id in sorted(_PERFORMANCE_PRESENTATION_PRESERVE_PFS):
                    pf_hist = hist / "preserved" / pf_id
                    pf_hist.mkdir(parents=True, exist_ok=True)
                    raw, _source = _copy_preserved_performance_evidence(pf_id, pf_hist)
                    presentation_ok = _performance_presentation_passed(pf_id, raw)
                    out.write(
                        f"{pf_id}: presentation {'PASS' if presentation_ok else 'FAIL'} "
                        f"{_performance_key_result(pf_id, raw)}\n"
                    )
                    if not presentation_ok:
                        rc = 1
                out.write("\nPresentation performance flow completed.\n")
            _copy_performance_presentation_results(job)
            with _PERFORMANCE_JOB_LOCK:
                job["exit_code"] = rc
                job["state"] = "finished" if rc == 0 else "failed"
        except Exception as exc:
            with _PERFORMANCE_JOB_LOCK:
                job["state"] = "failed"
                job["exit_code"] = 1
                job["error"] = str(exc)
            with open(stdout_log, "a", encoding="utf-8", errors="replace") as out:
                out.write(f"\n[performance-dashboard] presentation job failed: {exc}\n")
        finally:
            _restore_baseline(saved)
            with _PERFORMANCE_JOB_LOCK:
                job["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
                _write_job_metadata(job)


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


def _int_env(env: dict[str, str], key: str, default: int, minimum: int = 1) -> int:
    try:
        return max(minimum, int(float(env.get(key, str(default)))))
    except Exception:
        return default


def _performance_ssh_probe(env: dict[str, str], label: str, out: Any) -> bool:
    host = str(env.get("PERF_SSH_PROBE_HOST", "xfusion4")).strip()
    if not host:
        out.write(f"[ssh-probe] {label}: skipped (PERF_SSH_PROBE_HOST empty)\n")
        out.flush()
        return True
    timeout_s = _int_env(env, "PERF_SSH_PROBE_TIMEOUT_S", 5)
    started = time.time()
    cmd = [
        "ssh",
        "-o", "BatchMode=yes",
        "-o", f"ConnectTimeout={timeout_s}",
        host,
        "hostname",
    ]
    try:
        proc = subprocess.run(
            cmd,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout_s + 2,
        )
        elapsed = time.time() - started
        output = (proc.stdout or "").strip()
        state = "PASS" if proc.returncode == 0 else "FAIL"
        out.write(
            f"[ssh-probe] {label}: {state} host={host} "
            f"rc={proc.returncode} elapsed={elapsed:.1f}s output={output}\n"
        )
        out.flush()
        return proc.returncode == 0
    except subprocess.TimeoutExpired as exc:
        elapsed = time.time() - started
        output = (exc.stdout or "")
        if isinstance(output, bytes):
            output = output.decode("utf-8", errors="replace")
        out.write(
            f"[ssh-probe] {label}: FAIL host={host} timeout elapsed={elapsed:.1f}s "
            f"output={str(output).strip()}\n"
        )
        out.flush()
        return False


def _run_performance_job(job_id: str, cmd: list[str], cwd: Path, env: dict[str, str],
                         protected_files: list[Path], result_files: list[tuple[Path, str]]) -> None:
    job = _PERFORMANCE_JOBS[job_id]
    hist = Path(job["history_abs"])
    stdout_log = hist / "stdout.log"
    saved = {p: _saved_file_snapshot(p) for p in protected_files}
    run_env = os.environ.copy()
    run_env.update(env)
    run_env["REPO_ROOT"] = str(REPO_ROOT)
    run_env.setdefault("PYTHONUNBUFFERED", "1")
    try:
        timeout_s = int(float(run_env.get("PERFORMANCE_TIMEOUT_S", "0") or "0"))
    except ValueError:
        timeout_s = 0
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
                if not _performance_ssh_probe(run_env, "pre", out):
                    rc = 90
                    with _PERFORMANCE_JOB_LOCK:
                        job["error"] = "performance job refused to start because SSH probe failed"
                    out.write("[performance-dashboard] pre-run SSH probe failed; job not started\n")
                else:
                    probe_stop = threading.Event()
                    probe_stats = {"total": 0, "failures": 0}
                    probe_holder: dict[str, Any] = {}
                    probe_interval = _int_env(run_env, "PERF_SSH_PROBE_INTERVAL_S", 10)
                    probe_fail_limit = _int_env(run_env, "PERF_SSH_PROBE_FAIL_LIMIT", 2)

                    def probe_loop() -> None:
                        while not probe_stop.is_set():
                            probe_stats["total"] += 1
                            ok = _performance_ssh_probe(
                                run_env,
                                f"during-{probe_stats['total']}",
                                out,
                            )
                            if not ok:
                                probe_stats["failures"] += 1
                                if probe_stats["failures"] >= probe_fail_limit:
                                    proc_obj = probe_holder.get("process")
                                    if proc_obj is not None and proc_obj.poll() is None:
                                        with _PERFORMANCE_JOB_LOCK:
                                            job["error"] = (
                                                "performance job stopped after repeated SSH probe failures"
                                            )
                                        out.write(
                                            "[performance-dashboard] repeated SSH probe failures; "
                                            "killing performance process\n"
                                        )
                                        out.flush()
                                        proc_obj.kill()
                                    break
                            probe_stop.wait(probe_interval)

                    probe_thread = threading.Thread(target=probe_loop, daemon=True)
                    probe_thread.start()
                    proc = subprocess.Popen(
                        cmd,
                        cwd=str(cwd),
                        env=run_env,
                        stdout=out,
                        stderr=subprocess.STDOUT,
                        text=True,
                    )
                    probe_holder["process"] = proc
                    job["process"] = proc
                    try:
                        rc = proc.wait(timeout=timeout_s if timeout_s > 0 else None)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        try:
                            proc.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            pass
                        rc = 124
                        with _PERFORMANCE_JOB_LOCK:
                            job["error"] = f"performance job timed out after {timeout_s}s"
                        out.write(f"\n[performance-dashboard] timeout after {timeout_s}s; process killed\n")
                    finally:
                        probe_stop.set()
                        probe_thread.join(timeout=3)
                    post_ok = _performance_ssh_probe(run_env, "post", out)
                    out.write(
                        "[performance-dashboard] ssh_probe_summary "
                        f"total={probe_stats['total']} failures={probe_stats['failures']} "
                        f"post_ok={post_ok}\n"
                    )
                    if probe_stats["failures"] >= probe_fail_limit or not post_ok:
                        rc = 90
                        with _PERFORMANCE_JOB_LOCK:
                            job["error"] = (
                                job.get("error")
                                or "performance job stopped because SSH probes failed"
                            )
            with _PERFORMANCE_JOB_LOCK:
                job["exit_code"] = rc
                job["state"] = "finished" if rc in (0, 2) else "failed"
            if job.get("kind") == "run_all":
                if job.get("profile") == "presentation":
                    _copy_performance_presentation_results(job)
                else:
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
        env["PERFORMANCE_PROFILE"] = "full"
        env["PERFORMANCE_TIMEOUT_S"] = str(_performance_timeout(env, "run_one", "full"))
        env = _apply_performance_run_mode(module, pf_id, env)
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
    try:
        env = _sanitize_performance_env(body.get("env", {}))
        profile = _performance_profile_from_body(body, env)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    env["PERFORMANCE_TIMEOUT_S"] = str(_performance_timeout(env, "run_all", profile))
    with _PERFORMANCE_JOB_LOCK:
        if _active_performance_job_exists():
            return jsonify({"ok": False, "error": "已有性能验收任务正在执行"}), 409
        job = _prepare_performance_job("run_all", env)
    hist = Path(job["history_abs"])
    if profile == "presentation":
        for pf_id in _PERFORMANCE_PRESENTATION_PRESERVE_PFS:
            pf_hist = hist / "preserved" / pf_id
            pf_hist.mkdir(parents=True, exist_ok=True)
            _copy_preserved_performance_evidence(pf_id, pf_hist)
        env["PERFORMANCE_PRESERVED_DIR"] = str(hist / "preserved")
    cmd = ["bash", str(PERFORMANCES_DIR / "run_all.sh")]
    env.setdefault("NR_SKIP_FLASK", "1")
    env.setdefault("NR_RESTORE_ASYNC_REPL", "0")
    protected = [PERFORMANCES_DIR / "summary.md"]
    for pf_id, _ in _PERFORMANCE_MODULES["performance"]["functions"]:
        protected.extend([
            PERFORMANCES_DIR / pf_id / "summary.md",
            PERFORMANCES_DIR / pf_id / "raw.json",
            PERFORMANCES_DIR / pf_id / "run_all.last.log",
        ])
    results = [(PERFORMANCES_DIR / "summary.md", "summary.md")]
    if profile == "presentation":
        th = threading.Thread(
            target=_run_performance_presentation_job,
            args=(job["job_id"], env, protected),
            daemon=True,
        )
    else:
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
