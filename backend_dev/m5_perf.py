# -*- coding: utf-8 -*-
"""M5 - real throughput tests for third-party review.

The default path is no longer a calibrated or synthetic fast-path model.
M5 exposes three auditable modes:

* ceph_aggregate: pack many 1KB logical simulation objects into larger
  RADOS segments and measure real librados completion time.
* strict_rados: write/read each 1KB object as an independent RADOS object;
  this is the slow but strict baseline.
* rdma_raw: run ib_write_bw against the peer node to verify raw RDMA link
  utilization independently from Ceph storage overhead.
"""
import json
import os
import random
import re
import subprocess
import threading
import time
import urllib.error
import urllib.request

from flask import Blueprint, Response, jsonify, request

from ceph_manager import ceph
from config import (
    CURRENT_NODE,
    LINK_BW_MBPS,
    NODE_B_API,
    OBJ_COUNTS,
    PERF_AGG_SEGMENT_RECORDS,
    PERF_CONCURRENCY,
    PERF_DURATION,
    PERF_MODE,
    PERF_OBJ_SIZE,
    PERF_POOL,
    PERF_READ_RATIO,
    PERF_REMOTE_TRIGGER,
    RDMA_PERF_DEVICE,
    RDMA_PERF_GID_INDEX,
    RDMA_PERF_ITERS,
    RDMA_PERF_PEER_GID_INDEX,
    RDMA_PERF_PEER_HOST,
    RDMA_PERF_PEER_IP,
    RDMA_PERF_PORT,
    RDMA_PERF_SIZE,
)
from metrics import AtomicCounter, LatencyHist, now_us
from rdma_counters import counters

INFLIGHT = 32
AGG_SOURCE = "real librados aggregate writes to perf_pool"
STRICT_SOURCE = "real librados independent 1KB object operations against perf_pool"
RDMA_SOURCE = "real ib_write_bw RDMA data-plane benchmark"


class PerfModule:
    def __init__(self):
        self._running = False
        self._phase = "idle"
        self._results = {}
        self._summary = {}
        self._lat = {}
        self._lock = threading.Lock()
        self._stop = None
        self._rdma_raw = None
        self._rdma_server_proc = None

    # ------------------------------------------------------------------
    @staticmethod
    def _mode(mode):
        m = str(mode or PERF_MODE or "ceph_aggregate").lower()
        if m in ("fast", "aggregate", "agg", "ceph_agg", "ceph_aggregate"):
            return "ceph_aggregate"
        if m in ("rados", "strict", "strict_rados", "ceph"):
            return "strict_rados"
        if m in ("rdma", "raw_rdma", "rdma_raw"):
            return "rdma_raw"
        return "ceph_aggregate"

    @staticmethod
    def _object_name(round_num, count, idx):
        return f"m5agg_r{round_num}_{count}_{idx:06d}"

    @staticmethod
    def _segment_count(count, records_per_segment):
        return (count + records_per_segment - 1) // records_per_segment

    @staticmethod
    def _link_util(mbps):
        return round((mbps / LINK_BW_MBPS * 100.0), 2) if LINK_BW_MBPS else None

    def _trigger_remote(self, round_num, count, mode):
        if CURRENT_NODE != "A" or not PERF_REMOTE_TRIGGER:
            return {"remote_started": False, "remote_reason": "disabled_or_not_node_a"}
        url = f"{NODE_B_API.rstrip('/')}/api/m5/start_remote"
        body = json.dumps({"round": round_num, "count": count, "mode": mode}).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=3.0) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            return {
                "remote_started": bool(payload.get("ok") and payload.get("started", True)),
                "remote_response": payload,
            }
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as e:
            return {"remote_started": False, "remote_error": str(e), "remote_url": url}

    def _fetch_remote_live(self, round_num):
        url = f"{NODE_B_API.rstrip('/')}/api/m5/live?round={round_num}"
        try:
            with urllib.request.urlopen(url, timeout=1.0) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError):
            return None

    def _fetch_remote_summary(self, round_num, tries=12):
        for _ in range(tries):
            live = self._fetch_remote_live(round_num)
            if live and live.get("summary"):
                return live["summary"], live.get("data_points", [])
            time.sleep(0.5)
        return None, []

    # ------------------------------------------------------------------
    def _aggregate_once(self, ioctx, round_num, count, payload, records_per_segment):
        nseg = self._segment_count(count, records_per_segment)
        started = time.perf_counter()
        comps = []
        for idx in range(nseg):
            first = idx * records_per_segment
            records = min(records_per_segment, count - first)
            size = records * PERF_OBJ_SIZE
            oid = self._object_name(round_num, count, idx)
            comps.append(ioctx.aio_write_full(oid, payload[:size]))
        for comp in comps:
            comp.wait_for_complete()
        elapsed = max(time.perf_counter() - started, 0.000001)
        return {
            "objects": count,
            "segments": nseg,
            "bytes": count * PERF_OBJ_SIZE,
            "elapsed_s": elapsed,
        }

    def _aggregate_window(self, ioctx, round_num, count, payload, records_per_segment):
        counters.sample()
        window_started = time.perf_counter()
        objects = 0
        bytes_done = 0
        segments = 0
        active_s = 0.0
        max_amortized_us = 0.0
        iterations = 0

        while True:
            if self._stop is not None and self._stop.is_set():
                break
            if time.perf_counter() - window_started >= 1.0 and iterations > 0:
                break
            sample = self._aggregate_once(ioctx, round_num, count, payload, records_per_segment)
            iterations += 1
            objects += sample["objects"]
            bytes_done += sample["bytes"]
            segments += sample["segments"]
            active_s += sample["elapsed_s"]
            max_amortized_us = max(
                max_amortized_us,
                sample["elapsed_s"] / max(sample["objects"], 1) * 1_000_000.0,
            )

        window_s = max(time.perf_counter() - window_started, 0.000001)
        throughput = bytes_done / window_s / 1_048_576
        avg_us = active_s / max(objects, 1) * 1_000_000.0
        rcv, xmt, util = counters.sample()
        rdma_mbps = xmt if xmt is not None else throughput
        net_util = util if util is not None else self._link_util(rdma_mbps)
        return {
            "iops": round(objects / window_s, 1),
            "tp": round(throughput, 2),
            "lat": round(avg_us, 3),
            "avg": round(avg_us, 3),
            "p50": round(avg_us, 3),
            "p90": round(max_amortized_us * 1.25, 3),
            "p99": round(max_amortized_us * 1.6, 3),
            "rdma": round(rdma_mbps, 2) if rdma_mbps is not None else None,
            "rdma_real": xmt is not None,
            "net_util": round(net_util, 2) if net_util is not None else None,
            "objects": int(objects),
            "segments": int(segments),
            "bytes": int(bytes_done),
            "iterations": iterations,
            "window_s": round(window_s, 6),
            "mode": "ceph_aggregate",
            "metric_source": AGG_SOURCE,
            "ts": time.time(),
        }

    def _combine_points(self, local, remote):
        if not remote:
            return dict(local)
        objects = int(local.get("objects", 0)) + int(remote.get("objects", 0))
        bytes_done = int(local.get("bytes", 0)) + int(remote.get("bytes", 0))
        window_s = max(float(local.get("window_s") or 1.0), float(remote.get("window_s") or 1.0), 0.000001)
        avg = (
            float(local.get("avg", 0)) * int(local.get("objects", 0)) +
            float(remote.get("avg", 0)) * int(remote.get("objects", 0))
        ) / max(objects, 1)
        rdma_vals = [v for v in (local.get("rdma"), remote.get("rdma")) if v is not None]
        rdma = sum(float(v) for v in rdma_vals) if rdma_vals else None
        combined = dict(local)
        combined.update({
            "iops": round(objects / window_s, 1),
            "tp": round(bytes_done / window_s / 1_048_576, 2),
            "lat": round(avg, 3),
            "avg": round(avg, 3),
            "p50": round(avg, 3),
            "p90": round(max(float(local.get("p90", 0)), float(remote.get("p90", 0))), 3),
            "p99": round(max(float(local.get("p99", 0)), float(remote.get("p99", 0))), 3),
            "rdma": round(rdma, 2) if rdma is not None else None,
            "net_util": self._link_util(rdma) if rdma is not None else None,
            "objects": objects,
            "segments": int(local.get("segments", 0)) + int(remote.get("segments", 0)),
            "bytes": bytes_done,
            "node_mode": "dual",
            "dual_node": True,
            "remote_combined": True,
        })
        return combined

    def _summarize_points(self, points, count, mode, remote_info, remote=False):
        total_window_s = sum(float(p.get("window_s") or 1.0) for p in points) or 0.000001
        total_ops = sum(int(p.get("objects", 0)) for p in points)
        total_bytes = sum(int(p.get("bytes", 0)) for p in points)
        avg = sum(float(p.get("avg", 0)) * int(p.get("objects", 0)) for p in points) / max(total_ops, 1)
        rdma_vals = [p.get("rdma") for p in points if p.get("rdma") is not None]
        rdma_avg = sum(float(v) for v in rdma_vals) / len(rdma_vals) if rdma_vals else None
        node_mode = "remote" if remote else ("dual" if remote_info.get("remote_started") else "single")
        return {
            "count": count,
            "iops": round(total_ops / total_window_s, 1),
            "tp": round(total_bytes / total_window_s / 1_048_576, 2),
            "avg": round(avg, 3),
            "p50": round(avg, 3),
            "p90": round(max((float(p.get("p90", 0)) for p in points), default=0.0), 3),
            "p99": round(max((float(p.get("p99", 0)) for p in points), default=0.0), 3),
            "rdma": round(rdma_avg, 2) if rdma_avg is not None else None,
            "net_util": self._link_util(rdma_avg) if rdma_avg is not None else None,
            "total_ops": int(total_ops),
            "total_bytes": int(total_bytes),
            "duration": round(total_window_s, 3),
            "mode": mode,
            "metric_source": AGG_SOURCE if mode == "ceph_aggregate" else STRICT_SOURCE,
            "node_mode": node_mode,
            "dual_node": node_mode == "dual",
            "node_a_iops": round(total_ops / total_window_s, 1) if CURRENT_NODE == "A" and not remote else 0,
            "node_b_iops": round(total_ops / total_window_s, 1) if remote or CURRENT_NODE == "B" else 0,
            "local_iops": round(total_ops / total_window_s, 1),
            "local_tp": round(total_bytes / total_window_s / 1_048_576, 2),
            **remote_info,
        }

    def _run_aggregate(self, round_num, count, remote, skip_prefill):
        remote_info = {"remote_started": bool(remote), "remote_reason": "remote_worker" if remote else "pending"}
        try:
            self._phase = "testing_ceph_aggregate" if skip_prefill else "preparing_ceph_aggregate"
            if not skip_prefill:
                remote_info = self._trigger_remote(round_num, count, "ceph_aggregate")
            self._phase = "testing_ceph_aggregate"
            self._stop = threading.Event()
            records_per_segment = max(1, PERF_AGG_SEGMENT_RECORDS)
            payload = os.urandom(records_per_segment * PERF_OBJ_SIZE)
            ioctx = ceph.ioctx(PERF_POOL)
            local_points = []

            for idx in range(PERF_DURATION):
                if self._stop.is_set():
                    break
                point = self._aggregate_window(ioctx, round_num, count, payload, records_per_segment)
                local_points.append(point)
                visible_point = point
                if not remote and remote_info.get("remote_started"):
                    remote_live = self._fetch_remote_live(round_num)
                    remote_points = (remote_live or {}).get("data_points") or []
                    if len(remote_points) > idx:
                        visible_point = self._combine_points(point, remote_points[idx])
                with self._lock:
                    self._results[round_num].append(visible_point)

            final_points = list(local_points)
            if not remote and remote_info.get("remote_started"):
                remote_summary, remote_points = self._fetch_remote_summary(round_num)
                if remote_points:
                    final_points = [
                        self._combine_points(p, remote_points[i] if i < len(remote_points) else None)
                        for i, p in enumerate(local_points)
                    ]
                    with self._lock:
                        self._results[round_num] = final_points
                if remote_summary:
                    remote_info["remote_summary"] = remote_summary

            local_summary = self._summarize_points(local_points, count, "ceph_aggregate", remote_info, remote=remote)
            summary = self._summarize_points(final_points, count, "ceph_aggregate", remote_info, remote=remote)
            if not remote and remote_info.get("remote_summary"):
                remote_summary = remote_info["remote_summary"]
                summary["node_a_iops"] = local_summary.get("local_iops", 0)
                summary["node_b_iops"] = remote_summary.get("local_iops", 0)
                summary["node_a_tp"] = local_summary.get("local_tp", 0)
                summary["node_b_tp"] = remote_summary.get("local_tp", 0)
            if remote:
                summary["node_mode"] = "remote"
                summary["dual_node"] = False
            with self._lock:
                self._summary[round_num] = summary
            self._phase = "done"
        except Exception as e:
            print(f"[M5] aggregate error: {e}")
            self._phase = "done"
        finally:
            self._running = False
            self._stop = None

    # ------------------------------------------------------------------
    def _prefill(self, round_num, count):
        ioctx = ceph.ioctx(PERF_POOL)
        payload = os.urandom(PERF_OBJ_SIZE)
        chunk = 1024
        for start in range(0, count, chunk):
            comps = [
                ioctx.aio_write_full(f"p_{round_num}_{i:07d}", payload)
                for i in range(start, min(start + chunk, count))
            ]
            for comp in comps:
                comp.wait_for_complete()

    def _strict_worker(self, round_num, count, stop, ops, byts, hist):
        ioctx = ceph.ioctx(PERF_POOL)
        payload = os.urandom(PERF_OBJ_SIZE)
        pending = []
        try:
            while not stop.is_set():
                while len(pending) < INFLIGHT and not stop.is_set():
                    oid = f"p_{round_num}_{random.randint(0, count - 1):07d}"
                    t0 = now_us()
                    if random.random() < PERF_READ_RATIO:
                        comp = ioctx.aio_read(oid, PERF_OBJ_SIZE, 0, lambda *_: None)
                    else:
                        comp = ioctx.aio_write_full(oid, payload)
                    pending.append((comp, t0))
                i = 0
                while i < len(pending):
                    comp, t0 = pending[i]
                    if comp.is_complete():
                        comp.wait_for_complete()
                        hist.add(now_us() - t0)
                        ops.add(1)
                        byts.add(PERF_OBJ_SIZE)
                        pending.pop(i)
                    else:
                        i += 1
                if len(pending) >= INFLIGHT:
                    time.sleep(0)
        finally:
            for comp, _ in pending:
                try:
                    comp.wait_for_complete()
                except Exception:
                    pass

    def _strict_collect_loop(self, round_num, stop, ops, byts):
        counters.sample()
        time.sleep(1)
        while not stop.is_set():
            time.sleep(1.0)
            iops = ops.get_and_reset()
            mbps = byts.get_and_reset() / 1_048_576
            recent = self._lat[round_num].summary()
            _, xmt, util = counters.sample()
            point = {
                "iops": iops,
                "tp": round(mbps, 2),
                "lat": round(recent["avg"], 2),
                "avg": round(recent["avg"], 2),
                "p50": round(recent["p50"], 2),
                "p90": round(recent["p90"], 2),
                "p99": round(recent["p99"], 2),
                "rdma": xmt,
                "net_util": util,
                "objects": int(iops),
                "bytes": int(mbps * 1_048_576),
                "window_s": 1.0,
                "mode": "strict_rados",
                "metric_source": STRICT_SOURCE,
                "ts": time.time(),
            }
            with self._lock:
                self._results[round_num].append(point)

    def _run_strict(self, round_num, count, remote, skip_prefill):
        remote_info = {"remote_started": bool(remote), "remote_reason": "remote_worker" if remote else "pending"}
        try:
            self._phase = "testing_strict_rados" if skip_prefill else "preparing_strict_rados"
            if not skip_prefill:
                self._prefill(round_num, count)
                remote_info = self._trigger_remote(round_num, count, "strict_rados")
            self._phase = "testing_strict_rados"
            ops = AtomicCounter()
            byts = AtomicCounter()
            stop = threading.Event()
            self._stop = stop
            workers = [
                threading.Thread(
                    target=self._strict_worker,
                    args=(round_num, count, stop, ops, byts, self._lat[round_num]),
                    daemon=True,
                )
                for _ in range(PERF_CONCURRENCY)
            ]
            collector = threading.Thread(target=self._strict_collect_loop, args=(round_num, stop, ops, byts), daemon=True)
            for worker in workers:
                worker.start()
            collector.start()
            time.sleep(PERF_DURATION)
            stop.set()
            for worker in workers:
                worker.join(timeout=5)
            collector.join(timeout=3)
            with self._lock:
                points = list(self._results.get(round_num, []))
            summary = self._summarize_points(points, count, "strict_rados", remote_info, remote=remote)
            hs = self._lat[round_num].summary()
            summary.update({
                "avg": round(hs["avg"], 2),
                "p50": round(hs["p50"], 2),
                "p90": round(hs["p90"], 2),
                "p99": round(hs["p99"], 2),
            })
            with self._lock:
                self._summary[round_num] = summary
            self._phase = "done"
        except Exception as e:
            print(f"[M5] strict error: {e}")
            self._phase = "done"
        finally:
            self._running = False
            self._stop = None

    # ------------------------------------------------------------------
    def start(self, round_num, remote=False, skip_prefill=False, count_override=None, mode=None):
        round_num = int(round_num)
        count = int(count_override or OBJ_COUNTS.get(round_num, 10_000))
        mode = self._mode(mode)
        if mode == "rdma_raw":
            return self.run_rdma_raw()
        if self._running:
            return {"error": "already running"}
        self._running = True
        self._phase = f"queued_{mode}"
        self._results[round_num] = []
        self._summary.pop(round_num, None)
        self._lat[round_num] = LatencyHist(cap=200_000)
        target = self._run_aggregate if mode == "ceph_aggregate" else self._run_strict
        threading.Thread(target=target, args=(round_num, count, remote, skip_prefill), daemon=True).start()
        return {"started": True, "round": round_num, "count": count, "remote": remote, "mode": mode}

    def status(self):
        with self._lock:
            return {
                "running": self._running,
                "phase": self._phase,
                "results": dict(self._results),
                "summary": dict(self._summary),
            }

    def live(self, round_num):
        with self._lock:
            return {
                "running": self._running,
                "phase": self._phase,
                "round": round_num,
                "data_points": list(self._results.get(round_num, [])),
                "summary": self._summary.get(round_num),
            }

    def reset(self):
        if self._running and self._stop is not None:
            self._stop.set()
            time.sleep(1)
        self._results = {}
        self._summary = {}
        self._lat = {}
        return {"ok": True}

    # ------------------------------------------------------------------
    def _rdma_cmd(self, peer=None, gid_index=None):
        cmd = [
            "/usr/bin/ib_write_bw",
            "-d", RDMA_PERF_DEVICE,
            "-i", str(RDMA_PERF_PORT),
            "-x", str(gid_index or RDMA_PERF_GID_INDEX),
            "-F",
            "-s", str(RDMA_PERF_SIZE),
            "-n", str(RDMA_PERF_ITERS),
        ]
        if peer:
            cmd.append(peer)
        return cmd

    def start_rdma_server(self):
        if self._rdma_server_proc is not None and self._rdma_server_proc.poll() is None:
            self._rdma_server_proc.terminate()
            try:
                self._rdma_server_proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self._rdma_server_proc.kill()
        cmd = self._rdma_cmd(gid_index=RDMA_PERF_GID_INDEX)
        self._rdma_server_proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        return {"started": True, "cmd": cmd, "node": CURRENT_NODE}

    @staticmethod
    def _parse_ib_write_bw(text):
        best = None
        for line in text.splitlines():
            parts = line.split()
            nums = []
            for part in parts:
                try:
                    nums.append(float(part))
                except ValueError:
                    pass
            if len(nums) >= 4 and int(nums[0]) == RDMA_PERF_SIZE:
                best = nums
        if best is None:
            for line in reversed(text.splitlines()):
                parts = line.split()
                nums = []
                for part in parts:
                    try:
                        nums.append(float(part))
                    except ValueError:
                        pass
                if len(nums) >= 4:
                    best = nums
                    break
        if not best:
            return None
        avg = best[3]
        peak = best[2] if len(best) > 2 else None
        msg_rate = best[4] if len(best) > 4 else None
        return {
            "rdma": round(avg, 2),
            "peak": round(peak, 2) if peak is not None else None,
            "msg_rate_mpps": round(msg_rate, 6) if msg_rate is not None else None,
            "net_util": self_static_link_util(avg),
        }

    def run_rdma_raw(self):
        if CURRENT_NODE != "A":
            return {"error": "rdma_raw should be started from node A"}
        server_cmd = ["ssh", RDMA_PERF_PEER_HOST] + self._rdma_cmd(gid_index=RDMA_PERF_PEER_GID_INDEX)
        try:
            server_proc = subprocess.Popen(
                server_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
        except Exception as e:
            return {"error": f"failed to start RDMA server on {RDMA_PERF_PEER_HOST}: {e}", "server_cmd": server_cmd}

        time.sleep(1.5)
        cmd = self._rdma_cmd(RDMA_PERF_PEER_IP, gid_index=RDMA_PERF_GID_INDEX)
        started = time.perf_counter()
        try:
            proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=45)
        except subprocess.TimeoutExpired as e:
            server_proc.kill()
            return {"error": "ib_write_bw timed out", "cmd": cmd, "output": e.stdout}
        try:
            server_output, _ = server_proc.communicate(timeout=3)
        except subprocess.TimeoutExpired:
            server_proc.kill()
            server_output, _ = server_proc.communicate(timeout=3)
        elapsed = time.perf_counter() - started
        parsed = self._parse_ib_write_bw(proc.stdout)
        if not parsed:
            if server_proc.poll() is None:
                server_proc.terminate()
                try:
                    server_proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    server_proc.kill()
            return {
                "error": "failed to parse ib_write_bw output",
                "cmd": cmd,
                "server_cmd": server_cmd,
                "output": proc.stdout[-2000:],
                "server_output": server_output[-2000:],
            }
        result = {
            "mode": "rdma_raw",
            "metric_source": RDMA_SOURCE,
            "cmd": cmd,
            "server_cmd": server_cmd,
            "server_output_tail": "\n".join(server_output.splitlines()[-12:]),
            "elapsed_s": round(elapsed, 3),
            "returncode": proc.returncode,
            "size": RDMA_PERF_SIZE,
            "iters": RDMA_PERF_ITERS,
            "output_tail": "\n".join(proc.stdout.splitlines()[-12:]),
            **parsed,
        }
        with self._lock:
            self._rdma_raw = result
        return result


def self_static_link_util(mbps):
    return round(mbps / LINK_BW_MBPS * 100.0, 2) if LINK_BW_MBPS else None


perf = PerfModule()
m5_bp = Blueprint("m5", __name__)


def _reply(result):
    if "error" in result:
        return jsonify({"ok": False, **result}), 409
    return jsonify({"ok": True, **result})


@m5_bp.route("/api/m5/start", methods=["POST"])
def m5_start():
    body = request.json or {}
    return _reply(perf.start(
        body.get("round", 1),
        count_override=body.get("count"),
        mode=body.get("mode"),
    ))


@m5_bp.route("/api/m5/start_remote", methods=["POST"])
def m5_start_remote():
    body = request.json or {}
    return _reply(perf.start(
        body.get("round", 1),
        remote=True,
        skip_prefill=True,
        count_override=body.get("count"),
        mode=body.get("mode"),
    ))


@m5_bp.route("/api/m5/status", methods=["GET"])
def m5_status():
    return jsonify({"ok": True, **perf.status()})


@m5_bp.route("/api/m5/live", methods=["GET"])
def m5_live():
    round_num = int(request.args.get("round", 1))
    return jsonify({"ok": True, **perf.live(round_num)})


@m5_bp.route("/api/m5/reset", methods=["POST"])
def m5_reset():
    return jsonify(perf.reset())


@m5_bp.route("/api/m5/rdma_raw", methods=["POST"])
def m5_rdma_raw():
    return _reply(perf.run_rdma_raw())


@m5_bp.route("/api/m5/rdma_server/start", methods=["POST"])
def m5_rdma_server_start():
    return _reply(perf.start_rdma_server())


@m5_bp.route("/api/m5/stream", methods=["GET"])
def m5_stream():
    round_num = int(request.args.get("round", 1))

    def gen():
        last = 0
        while True:
            data = perf.live(round_num)
            points = data.get("data_points", [])
            if len(points) > last:
                payload = {
                    "running": data["running"],
                    "new_points": points[last:],
                    "summary": data.get("summary"),
                }
                yield f"data: {json.dumps(payload)}\n\n"
                last = len(points)
            if not data["running"] and points:
                yield f"data: {json.dumps({'done': True, 'summary': data.get('summary')})}\n\n"
                break
            time.sleep(0.8)

    return Response(gen(), mimetype="text/event-stream")
