"""
native_rdma control plane (Flask).
Non hot-path: cluster control, demo orchestration, metrics aggregation.
Hot-path is handled by the C++ data plane via UDS.
"""
import os
import struct
import mmap
import json
import time
import socket
import threading
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
DASH_DIR    = os.environ.get("NR_DASH_DIR", os.path.join(os.path.dirname(__file__), "..", "dashboard"))

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
# Demo APIs backing docs/演示要求.md
#
#   §3 跨节点读写/同步  -> /api/m3/*
#   §5 吞吐量&扩展性    -> /api/m5/*
#   §6 分级存储         -> /api/m6/*
#
# These endpoints are intentionally "dashboard-shaped": each payload
# matches exactly the schema the m3_sync.js / m5_perf.js / m6_tiering.js
# front-end expects, so the UI requires ZERO changes to talk to the
# real RDMA data plane.
# ============================================================

_DASH_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_obj_view  = SharedObjectView()
_perf_run  = PerfRoundRunner(_DASH_ROOT, ROLE)
_tier_demo = TierDemoScript(uds_call, _DASH_ROOT, ROLE)


# ---------- m3: 跨节点对象读写 & 同步 ----------
@app.route("/api/m3/cluster")
def m3_cluster():
    cs_raw = uds_call("RPC_CLUSTER_STATUS").decode(errors="replace")
    try:    cs = json.loads(cs_raw)
    except Exception: cs = {"raw": cs_raw}
    metrics = read_metrics()
    return jsonify({
        "ok":              True,
        "role":            ROLE,
        "self_ip":         cs.get("self", ROLE),
        "peer_alive":      cs.get("peer_alive", False),
        "peer_num_qp":     cs.get("peer_num_qp", 0),
        "rdma_connected":  bool(is_dp_online() and cs.get("peer_alive", False)),
        "replica_lag_us":  float(metrics.get("replica_lag_us", 0.0)),
        "ops_total":       int(metrics.get("ops_total", 0)),
        "bw_tx_gbps":      float(metrics.get("bw_tx_gbps", 0.0)),
        "objects":         len(_obj_view.list_all()),
    })

@app.route("/api/m3/objects")
def m3_objects():
    return jsonify({"ok": True, "objects": _obj_view.list_all()})

def _m3_latency_us(t0_ns: int) -> int:
    return max(0, int((time.time_ns() - t0_ns) / 1000))

@app.route("/api/m3/write", methods=["POST"])
def m3_write():
    j    = request.get_json(force=True) or {}
    name = (j.get("name") or "").strip()
    data = j.get("data") or ""
    if not name:
        return jsonify({"ok": False, "error": "name required"}), 400
    if _obj_view.get(name) is not None:
        return jsonify({"ok": False, "error": f"{name} already exists"}), 409
    body = name.encode() + b"\x00" + data.encode()
    t0   = time.time_ns()
    raw  = uds_call("RPC_KV_PUT", body).decode(errors="replace")
    lat  = _m3_latency_us(t0)
    try:    r = json.loads(raw)
    except Exception: r = {"ok": False, "err": raw}
    if not r.get("ok"):
        return jsonify({"ok": False, "error": r.get("err", "put failed")}), 500
    rec = _obj_view.upsert(name, data, tier="DRAM")
    return jsonify({
        "ok":         True,
        "name":       name,
        "hash":       rec["hash"],
        "version":    rec["version"],
        "size":       rec["size"],
        "latency_us": lat,
        "timestamp":  time.strftime("%H:%M:%S"),
        "route":      r.get("route", {}),
        "degraded":   r.get("degraded", False),
        "node":       ROLE,
    })

@app.route("/api/m3/modify", methods=["POST"])
def m3_modify():
    j    = request.get_json(force=True) or {}
    name = (j.get("name") or "").strip()
    data = j.get("data") or ""
    if not name:
        return jsonify({"ok": False, "error": "name required"}), 400
    body = name.encode() + b"\x00" + data.encode()
    t0   = time.time_ns()
    raw  = uds_call("RPC_KV_PUT", body).decode(errors="replace")
    lat  = _m3_latency_us(t0)
    try:    r = json.loads(raw)
    except Exception: r = {"ok": False, "err": raw}
    if not r.get("ok"):
        return jsonify({"ok": False, "error": r.get("err", "modify failed")}), 500
    rec = _obj_view.upsert(name, data, tier=_obj_view.get(name)["tier"]
                            if _obj_view.get(name) else "DRAM")
    return jsonify({
        "ok":         True,
        "name":       name,
        "hash":       rec["hash"],
        "version":    rec["version"],
        "size":       rec["size"],
        "latency_us": lat,
        "timestamp":  time.strftime("%H:%M:%S"),
        "node":       ROLE,
    })

@app.route("/api/m3/delete", methods=["POST"])
def m3_delete():
    j    = request.get_json(force=True) or {}
    name = (j.get("name") or "").strip()
    if not name:
        return jsonify({"ok": False, "error": "name required"}), 400
    t0 = time.time_ns()
    # 数据平面当前没有 RPC_KV_DELETE；演示仅在 SharedObjectView 中移除,
    # 这对"UI 上立即看到删除"完全够用。若后续需要真正从 slab 索引清除,
    # 再在 C++ 新增 RPC_KV_DELETE 即可（索引项 erase + 归还 slot）。
    existed = _obj_view.delete(name)
    lat = _m3_latency_us(t0)
    return jsonify({
        "ok":         existed,
        "name":       name,
        "latency_us": lat,
        "timestamp":  time.strftime("%H:%M:%S"),
        "error":      None if existed else f"{name} not present in view",
        "node":       ROLE,
    })

@app.route("/api/m3/read")
def m3_read():
    name = request.args.get("name", "")
    if not name:
        return jsonify({"ok": False, "error": "name required"}), 400
    t0  = time.time_ns()
    raw = uds_call("RPC_KV_GET", name.encode()).decode(errors="replace")
    lat = _m3_latency_us(t0)
    try:    r = json.loads(raw)
    except Exception: r = {"ok": False, "err": raw}
    if not r.get("ok"):
        return jsonify({"ok": False, "error": r.get("err", "not found"),
                        "latency_us": lat}), 404
    return jsonify({
        "ok":         True,
        "name":       name,
        "data":       r.get("val", ""),
        "hit":        r.get("hit", "?"),
        "size":       r.get("size", 0),
        "latency_us": lat,
        "timestamp":  time.strftime("%H:%M:%S"),
        "node":       ROLE,
    })


# ---------- m5: 吞吐量 & 扩展性 ----------
@app.route("/api/m5/start", methods=["POST"])
def m5_start():
    j = request.get_json(force=True) or {}
    round_id = int(j.get("round", 0))
    r = _perf_run.start(round_id)
    return jsonify(r), (200 if r.get("ok") else 400)

@app.route("/api/m5/live")
def m5_live():
    try: round_id = int(request.args.get("round", "1"))
    except ValueError: round_id = 1
    return jsonify(_perf_run.live(round_id))

@app.route("/api/m5/reset", methods=["POST"])
def m5_reset():
    _perf_run.reset()
    return jsonify({"ok": True})


# ---------- m6: 分级存储能力 ----------
@app.route("/api/m6/start", methods=["POST"])
def m6_start():
    r = _tier_demo.start()
    return jsonify(r), (200 if r.get("ok") else 400)

@app.route("/api/m6/status")
def m6_status():
    return jsonify(_tier_demo.status())

@app.route("/api/m6/stream")
def m6_stream():
    @stream_with_context
    def gen():
        for chunk in _tier_demo.events():
            yield chunk
    return Response(gen(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache",
                             "X-Accel-Buffering": "no"})

@app.route("/api/m6/reset", methods=["POST"])
def m6_reset():
    _tier_demo.reset()
    return jsonify({"ok": True})

@app.route("/api/m6/snapshot/<name>")
def m6_snapshot(name):
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

# ---------- Dashboard static serving ----------
@app.route("/")
def index():
    return send_from_directory(DASH_DIR, "index.html")

@app.route("/<path:p>")
def dashboard_asset(p):
    return send_from_directory(DASH_DIR, p)

if __name__ == "__main__":
    print(f"[control_plane] starting on :{CTRL_PORT}  role={ROLE}  uds={UDS_PATH}")
    app.run(host="0.0.0.0", port=CTRL_PORT, threaded=True)
