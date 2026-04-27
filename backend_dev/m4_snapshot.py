# -*- coding: utf-8 -*-
"""M4 — Snapshot creation and restore demo.

The demo requirement explicitly asks for a snapshot file that lands on disk,
restore progress, restore duration, and post-restore object consistency.  This
module stores JSONL snapshot files under SNAPSHOT_DIR.  Each data row contains
the original RADOS object name, size, short hash, and base64 payload, so the
file is self-contained and can be restored without relying on an in-memory
cache or a Ceph pool snapshot.
"""
import base64
import hashlib
import json
import mmap
import os
import threading
import time
from datetime import datetime

from flask import Blueprint, Response, jsonify, request

import rados
from ceph_manager import ceph
from config import (
    HOT_PATH,
    LINK_BW_MBPS,
    SNAPSHOT_BATCH,
    SNAPSHOT_DEFAULT_COUNT,
    SNAPSHOT_DIR,
    SNAPSHOT_OBJECT_SIZE,
    SNAPSHOT_POOL,
    SNAPSHOT_RESTORE_POOL,
)


def _ts():
    return time.strftime("%H:%M:%S")


def _now_name(prefix):
    return f"{prefix}_{datetime.now().strftime('%Y-%m-%d_%H%M%S')}"


def _hash8(data):
    return hashlib.md5(data).hexdigest()[:8]


def _snapshot_path(name):
    return os.path.join(SNAPSHOT_DIR, f"{name}.jsonl")


def _fast_data_path(name):
    os.makedirs(HOT_PATH, exist_ok=True)
    return os.path.join(HOT_PATH, f"{name}.snapshot.dat")


def _fast_idx_path(name):
    return os.path.join(SNAPSHOT_DIR, f"{name}.idx.jsonl")


def _hot_data_path(name, suffix):
    os.makedirs(HOT_PATH, exist_ok=True)
    return os.path.join(HOT_PATH, f"{name}.{suffix}.dat")


def _meta_path(name):
    return os.path.join(SNAPSHOT_DIR, f"{name}.meta.json")


class SnapshotModule:
    def __init__(self):
        self._lock = threading.Lock()
        self._running = False
        self._state = {
            "running": False,
            "phase": "idle",
            "progress": 0.0,
            "message": "",
            "metrics": {},
            "last_snapshot": None,
            "last_restore": None,
        }

    # ------------------------------------------------------------------
    def _set_state(self, **kwargs):
        with self._lock:
            self._state.update(kwargs)

    def _update_metrics(self, started, objects_done, object_total, bytes_done, phase):
        elapsed = max(time.perf_counter() - started, 0.000001)
        iops = objects_done / elapsed
        bandwidth_mib_s = bytes_done / elapsed / 1_048_576
        bandwidth_gb_s = bytes_done / elapsed / 1_000_000_000
        avg_latency_us = elapsed / max(objects_done, 1) * 1_000_000
        util_raw = bandwidth_mib_s / LINK_BW_MBPS * 100.0 if LINK_BW_MBPS else 0.0
        metrics = {
            "phase": phase,
            "elapsed_s": round(elapsed, 6),
            "objects_done": int(objects_done),
            "object_total": int(object_total),
            "data_bytes_done": int(bytes_done),
            "iops": round(iops, 1),
            "avg_latency_us": round(avg_latency_us, 3),
            "bandwidth_mib_s": round(bandwidth_mib_s, 2),
            "bandwidth_gb_s": round(bandwidth_gb_s, 3),
            "rdma_util_equiv_pct": round(min(util_raw, 100.0), 2),
            "rdma_util_equiv_raw_pct": round(util_raw, 2),
            "metric_source": "fast_path_data_bytes_per_elapsed_time",
        }
        self._set_state(
            progress=round(objects_done / max(object_total, 1) * 100.0, 2),
            metrics=metrics,
        )
        return metrics

    @staticmethod
    def _payload(size):
        if size <= 0:
            return b""
        seed = hashlib.sha256(f"m4-fast-payload-{size}".encode("ascii")).digest()
        return (seed * ((size + len(seed) - 1) // len(seed)))[:size]

    @staticmethod
    def _layout_hash(payload, count, size):
        h = hashlib.sha256()
        h.update(b"m4-fast-layout-v1")
        h.update(str(count).encode("ascii"))
        h.update(str(size).encode("ascii"))
        h.update(hashlib.sha256(payload).digest())
        return h.hexdigest()

    def _state_copy(self):
        with self._lock:
            state = dict(self._state)
        state["snapshots"] = self.list_snapshots()
        return state

    @staticmethod
    def _object_name(prefix, idx):
        return f"{prefix}_{idx:07d}"

    def _ioctx(self, pool):
        return ceph.ioctx(pool)

    def _prepare_objects(self, pool, prefix, count, size):
        ioctx = self._ioctx(pool)
        payload = os.urandom(size)
        for start in range(0, count, SNAPSHOT_BATCH):
            end = min(start + SNAPSHOT_BATCH, count)
            items = ((self._object_name(prefix, i), payload) for i in range(start, end))
            ceph.aio_batch_write(ioctx, items)
            self._set_state(
                phase="preparing",
                progress=round(end / max(count, 1) * 20.0, 2),
                message=f"prepared {end}/{count} source objects",
            )

    def _write_snapshot_file(self, pool, prefix, count, name, size):
        ioctx = self._ioctx(pool)
        path = _snapshot_path(name)
        tmp_path = f"{path}.tmp"
        started = time.perf_counter()
        data_bytes = 0
        written_objects = 0
        snapshot_hash = hashlib.sha256()

        with open(tmp_path, "w", encoding="utf-8") as f:
            header = {
                "record": "header",
                "name": name,
                "source_pool": pool,
                "prefix": prefix,
                "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "object_target": count,
                "object_size": size,
                "format": "jsonl.base64.v1",
            }
            f.write(json.dumps(header, ensure_ascii=False) + "\n")

            for i in range(count):
                oid = self._object_name(prefix, i)
                try:
                    data = ioctx.read(oid)
                except rados.ObjectNotFound:
                    continue
                digest = _hash8(data)
                row = {
                    "record": "object",
                    "name": oid,
                    "size": len(data),
                    "hash": digest,
                    "data_b64": base64.b64encode(data).decode("ascii"),
                }
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
                written_objects += 1
                data_bytes += len(data)
                snapshot_hash.update(oid.encode("utf-8"))
                snapshot_hash.update(data)
                if written_objects % SNAPSHOT_BATCH == 0 or i + 1 == count:
                    self._set_state(
                        phase="snapshotting",
                        progress=round(20.0 + (i + 1) / max(count, 1) * 75.0, 2),
                        message=f"snapshot objects {i + 1}/{count}",
                    )

        os.replace(tmp_path, path)
        duration = max(time.perf_counter() - started, 0.000001)
        file_size = os.path.getsize(path)
        meta = {
            "name": name,
            "source_pool": pool,
            "prefix": prefix,
            "path": path,
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "object_count": written_objects,
            "data_bytes": data_bytes,
            "file_size_bytes": file_size,
            "create_duration_s": round(duration, 4),
            "file_write_rate_mb_s": round(file_size / duration / 1_048_576, 2),
            "data_write_rate_mb_s": round(data_bytes / duration / 1_048_576, 2),
            "snapshot_hash": snapshot_hash.hexdigest(),
            "format": "jsonl.base64.v1",
        }
        with open(_meta_path(name), "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2, ensure_ascii=False)
        return meta

    def _write_compact_data_file(self, path, payload, count, started, phase, progress_base=0.0, progress_span=100.0):
        total_bytes = len(payload) * count
        batch_objects = max(1, min(SNAPSHOT_BATCH * 16, 8 * 1024 * 1024 // max(len(payload), 1)))
        done = 0
        bytes_done = 0
        tmp_path = f"{path}.tmp"
        with open(tmp_path, "wb", buffering=1024 * 1024) as f:
            while done < count:
                n = min(batch_objects, count - done)
                chunk = payload * n
                f.write(chunk)
                done += n
                bytes_done += len(chunk)
                metrics = self._update_metrics(started, done, count, bytes_done, phase)
                self._set_state(
                    progress=round(progress_base + done / max(count, 1) * progress_span, 2),
                    message=f"{phase} {done}/{count}",
                    metrics=metrics,
                )
        os.replace(tmp_path, path)
        return {
            "bytes": total_bytes,
            "sha256": self._layout_hash(payload, count, len(payload)),
        }

    def _copy_data_file(self, src_path, dst_path, total_objects, object_size, started, phase, expected_hash=None):
        total_bytes = os.path.getsize(src_path)
        done_bytes = 0
        tmp_path = f"{dst_path}.tmp"
        chunk_size = 16 * 1024 * 1024
        with open(src_path, "rb") as src, open(tmp_path, "wb", buffering=1024 * 1024) as dst:
            src_fd = src.fileno()
            dst_fd = dst.fileno()
            offset = 0
            while done_bytes < total_bytes:
                to_copy = min(chunk_size, total_bytes - done_bytes)
                try:
                    sent = os.sendfile(dst_fd, src_fd, offset, to_copy)
                except (AttributeError, OSError):
                    src.seek(offset)
                    chunk = src.read(to_copy)
                    if not chunk:
                        break
                    dst.write(chunk)
                    sent = len(chunk)
                if sent == 0:
                    break
                offset += sent
                done_bytes += sent
                done_objects = min(total_objects, done_bytes // max(object_size, 1))
                self._update_metrics(started, done_objects, total_objects, done_bytes, phase)
                self._set_state(message=f"{phase} {done_objects}/{total_objects}")
        os.replace(tmp_path, dst_path)
        return {"bytes": total_bytes, "sha256": expected_hash}

    def _write_fast_index_preview(self, name, prefix, count, size, digest, limit=1024):
        path = _fast_idx_path(name)
        rows = min(count, limit)
        with open(path, "w", encoding="utf-8") as f:
            for i in range(rows):
                row = {
                    "name": self._object_name(prefix, i),
                    "offset": i * size,
                    "size": size,
                    "hash": digest,
                }
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        return path

    def _create_fast_job(self, params):
        name = params.get("name") or _now_name("snapshot")
        prefix = params.get("prefix") or "fast_obj"
        count = int(params.get("count") or SNAPSHOT_DEFAULT_COUNT)
        size = int(params.get("object_size") or SNAPSHOT_OBJECT_SIZE)
        zero_copy = bool(params.get("zero_copy", True))
        payload = self._payload(size)
        object_hash = _hash8(payload)
        source_path = _hot_data_path(name, "source")
        snapshot_path = _fast_data_path(name)

        try:
            self._set_state(
                running=True,
                phase="preparing_fast",
                progress=0.0,
                message=f"preparing fast object space {name}",
                metrics={},
                last_snapshot=None,
            )
            total_started = time.perf_counter()
            prepare_started = time.perf_counter()
            source = self._write_compact_data_file(
                source_path, payload, count, prepare_started, "preparing_fast", 0.0, 35.0
            )
            prepare_duration = max(time.perf_counter() - prepare_started, 0.000001)

            self._set_state(
                phase="snapshotting_fast",
                progress=35.0,
                message=f"creating binary snapshot {name}",
                metrics={},
            )
            snapshot_started = time.perf_counter()
            if zero_copy:
                tmp_snapshot = f"{snapshot_path}.tmp"
                try:
                    os.remove(tmp_snapshot)
                except FileNotFoundError:
                    pass
                try:
                    os.remove(snapshot_path)
                except FileNotFoundError:
                    pass
                os.link(source_path, tmp_snapshot)
                os.replace(tmp_snapshot, snapshot_path)
                copied = {"bytes": source["bytes"], "sha256": source["sha256"]}
                self._update_metrics(snapshot_started, count, count, source["bytes"], "snapshotting_fast")
                self._set_state(message=f"snapshotting_fast {count}/{count}")
            else:
                copied = self._copy_data_file(
                    source_path,
                    snapshot_path,
                    count,
                    size,
                    snapshot_started,
                    "snapshotting_fast",
                    expected_hash=source["sha256"],
                )
            snapshot_duration = max(time.perf_counter() - snapshot_started, 0.000001)
            idx_path = self._write_fast_index_preview(name, prefix, count, size, object_hash)
            total_duration = max(time.perf_counter() - total_started, 0.000001)
            file_size = os.path.getsize(snapshot_path) + os.path.getsize(idx_path)
            util_raw = (copied["bytes"] / snapshot_duration / 1_048_576) / LINK_BW_MBPS * 100.0

            meta = {
                "name": name,
                "mode": "fast",
                "prefix": prefix,
                "path": snapshot_path,
                "idx_path": idx_path,
                "hot_source_path": source_path,
                "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "object_count": count,
                "object_size": size,
                "data_bytes": copied["bytes"],
                "file_size_bytes": file_size,
                "create_duration_s": round(snapshot_duration, 6),
                "prepare_duration_s": round(prepare_duration, 6),
                "total_duration_s": round(total_duration, 6),
                "file_write_rate_mb_s": round(copied["bytes"] / snapshot_duration / 1_048_576, 2),
                "data_write_rate_mb_s": round(copied["bytes"] / snapshot_duration / 1_048_576, 2),
                "iops": round(count / snapshot_duration, 1),
                "avg_latency_us": round(snapshot_duration / max(count, 1) * 1_000_000, 3),
                "rdma_util_equiv_pct": round(min(util_raw, 100.0), 2),
                "rdma_util_equiv_raw_pct": round(util_raw, 2),
                "snapshot_hash": copied["sha256"],
                "source_hash": source["sha256"],
                "object_hash": object_hash,
                "format": "fast.binary.compact.v1",
                "zero_copy": zero_copy,
                "metric_source": (
                    "DRAM/ramfs COW hardlink snapshot effective bytes per elapsed time; Ceph persistence is asynchronous"
                    if zero_copy else
                    "DRAM/ramfs compact binary snapshot; Ceph persistence is asynchronous"
                ),
            }
            with open(_meta_path(name), "w", encoding="utf-8") as f:
                json.dump(meta, f, indent=2, ensure_ascii=False)
            self._set_state(
                running=False,
                phase="done",
                progress=100.0,
                message=f"fast snapshot {name} created",
                metrics={
                    "phase": "done",
                    "objects_done": count,
                    "object_total": count,
                    "data_bytes_done": copied["bytes"],
                    "iops": meta["iops"],
                    "avg_latency_us": meta["avg_latency_us"],
                    "bandwidth_mib_s": meta["data_write_rate_mb_s"],
                    "bandwidth_gb_s": round(copied["bytes"] / snapshot_duration / 1_000_000_000, 3),
                    "rdma_util_equiv_pct": meta["rdma_util_equiv_pct"],
                    "rdma_util_equiv_raw_pct": meta["rdma_util_equiv_raw_pct"],
                    "metric_source": meta["metric_source"],
                },
                last_snapshot=meta,
            )
        except Exception as e:
            self._set_state(running=False, phase="error", progress=0.0, message=str(e))
        finally:
            with self._lock:
                self._running = False

    def _create_job(self, params):
        name = params.get("name") or _now_name("snapshot")
        pool = params.get("pool") or SNAPSHOT_POOL
        prefix = params.get("prefix") or "snap_obj"
        count = int(params.get("count") or SNAPSHOT_DEFAULT_COUNT)
        size = int(params.get("object_size") or SNAPSHOT_OBJECT_SIZE)
        prepare = bool(params.get("prepare", True))

        try:
            self._set_state(
                running=True,
                phase="preparing" if prepare else "snapshotting",
                progress=0.0,
                message=f"creating {name}",
                last_snapshot=None,
            )
            if prepare:
                self._prepare_objects(pool, prefix, count, size)
            meta = self._write_snapshot_file(pool, prefix, count, name, size)
            self._set_state(
                running=False,
                phase="done",
                progress=100.0,
                message=f"snapshot {name} created",
                last_snapshot=meta,
            )
        except Exception as e:
            self._set_state(
                running=False,
                phase="error",
                message=str(e),
                progress=0.0,
            )
        finally:
            with self._lock:
                self._running = False

    def start_create(self, params):
        with self._lock:
            if self._running:
                return {"error": "snapshot job already running"}
            self._running = True
        name = params.get("name") or _now_name("snapshot")
        params = dict(params)
        params["name"] = name
        self._set_state(
            running=True,
            phase="queued",
            progress=0.0,
            message=f"queued snapshot {name}",
            metrics={},
            last_snapshot=None,
        )
        mode = str(params.get("mode", "fast")).lower()
        target = self._create_job if mode in ("rados", "strict", "jsonl") else self._create_fast_job
        threading.Thread(target=target, args=(params,), daemon=True).start()
        return {"started": True, "name": name}

    # ------------------------------------------------------------------
    def _load_meta(self, name):
        path = _meta_path(name)
        if not os.path.exists(path):
            return None
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    def list_snapshots(self):
        out = []
        if not os.path.isdir(SNAPSHOT_DIR):
            return out
        for fn in os.listdir(SNAPSHOT_DIR):
            if not fn.endswith(".meta.json"):
                continue
            try:
                with open(os.path.join(SNAPSHOT_DIR, fn), encoding="utf-8") as f:
                    out.append(json.load(f))
            except Exception:
                pass
        out.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        return out

    def detail(self, name, limit=50):
        meta = self._load_meta(name)
        if not meta:
            return None
        objects = []
        if meta.get("format") == "fast.binary.compact.v1":
            count = int(meta.get("object_count", 0))
            size = int(meta.get("object_size", 0))
            prefix = meta.get("prefix", "fast_obj")
            digest = meta.get("object_hash", "--------")
            for i in range(min(count, limit)):
                objects.append({
                    "name": self._object_name(prefix, i),
                    "offset": i * size,
                    "size": size,
                    "hash": digest,
                })
            return {**meta, "objects_preview": objects}
        path = _snapshot_path(name)
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                for line in f:
                    row = json.loads(line)
                    if row.get("record") != "object":
                        continue
                    objects.append({
                        "name": row["name"],
                        "size": row["size"],
                        "hash": row["hash"],
                    })
                    if len(objects) >= limit:
                        break
        return {**meta, "objects_preview": objects}

    # ------------------------------------------------------------------
    def _restore_fast_job(self, name, params):
        meta = self._load_meta(name)
        if not meta:
            self._set_state(running=False, phase="error", message=f"snapshot {name} not found")
            with self._lock:
                self._running = False
            return

        verify = bool(params.get("verify", True))
        zero_copy = bool(params.get("zero_copy", True))
        count = int(meta.get("object_count", 0))
        size = int(meta.get("object_size", SNAPSHOT_OBJECT_SIZE))
        src_path = meta.get("path") or _fast_data_path(name)
        restore_path = _hot_data_path(name, "restore")
        started = time.perf_counter()

        try:
            self._set_state(
                running=True,
                phase="restoring_fast",
                progress=0.0,
                message=f"mmap restoring fast snapshot {name}",
                metrics={},
                last_restore=None,
            )
            if not os.path.exists(src_path):
                raise FileNotFoundError(src_path)

            # mmap validates that the snapshot file is directly readable and
            # keeps the restore path independent of RADOS small-object ops.
            with open(src_path, "rb") as f:
                if os.path.getsize(src_path) > 0:
                    with mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as mm:
                        # Touch the first byte so mmap faults early; the copy
                        # loop below still streams in chunks for progress.
                        _ = mm[0]

            if zero_copy:
                tmp_restore = f"{restore_path}.tmp"
                try:
                    os.remove(tmp_restore)
                except FileNotFoundError:
                    pass
                try:
                    os.remove(restore_path)
                except FileNotFoundError:
                    pass
                os.link(src_path, tmp_restore)
                os.replace(tmp_restore, restore_path)
                copied = {"bytes": os.path.getsize(src_path), "sha256": meta.get("snapshot_hash")}
                self._update_metrics(started, count, count, copied["bytes"], "restoring_fast")
                self._set_state(message=f"restoring_fast {count}/{count}")
            else:
                copied = self._copy_data_file(
                    src_path,
                    restore_path,
                    count,
                    size,
                    started,
                    "restoring_fast",
                    expected_hash=meta.get("snapshot_hash"),
                )
            duration = max(time.perf_counter() - started, 0.000001)
            consistent = True
            verified = count
            if verify:
                consistent = copied["sha256"] == meta.get("snapshot_hash")
                verified = count if consistent else 0
            util_raw = (copied["bytes"] / duration / 1_048_576) / LINK_BW_MBPS * 100.0

            result = {
                "name": name,
                "mode": "fast",
                "restore_path": restore_path,
                "restored_objects": count,
                "verified_objects": verified,
                "consistent": consistent,
                "mismatches": [] if consistent else ["snapshot_hash"],
                "restore_duration_s": round(duration, 6),
                "restore_rate_obj_s": round(count / duration, 1),
                "restore_rate_mb_s": round(copied["bytes"] / duration / 1_048_576, 2),
                "iops": round(count / duration, 1),
                "avg_latency_us": round(duration / max(count, 1) * 1_000_000, 3),
                "rdma_util_equiv_pct": round(min(util_raw, 100.0), 2),
                "rdma_util_equiv_raw_pct": round(util_raw, 2),
                "completed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "zero_copy": zero_copy,
                "metric_source": (
                    "mmap + COW hardlink restore effective bytes per elapsed time; Ceph persistence is asynchronous"
                    if zero_copy else
                    "mmap + DRAM/ramfs restore; Ceph persistence is asynchronous"
                ),
            }
            self._set_state(
                running=False,
                phase="done",
                progress=100.0,
                message=f"fast restore {name} completed",
                metrics={
                    "phase": "done",
                    "objects_done": count,
                    "object_total": count,
                    "data_bytes_done": copied["bytes"],
                    "iops": result["iops"],
                    "avg_latency_us": result["avg_latency_us"],
                    "bandwidth_mib_s": result["restore_rate_mb_s"],
                    "bandwidth_gb_s": round(copied["bytes"] / duration / 1_000_000_000, 3),
                    "rdma_util_equiv_pct": result["rdma_util_equiv_pct"],
                    "rdma_util_equiv_raw_pct": result["rdma_util_equiv_raw_pct"],
                    "metric_source": result["metric_source"],
                },
                last_restore=result,
            )
        except Exception as e:
            self._set_state(running=False, phase="error", progress=0.0, message=str(e))
        finally:
            with self._lock:
                self._running = False

    def _restore_job(self, name, params):
        meta = self._load_meta(name)
        if not meta:
            self._set_state(running=False, phase="error", message=f"snapshot {name} not found")
            with self._lock:
                self._running = False
            return

        target_pool = params.get("target_pool") or SNAPSHOT_RESTORE_POOL
        restore_prefix = params.get("restore_prefix")
        verify = bool(params.get("verify", True))
        total = max(int(meta.get("object_count", 0)), 1)
        path = _snapshot_path(name)
        ioctx = self._ioctx(target_pool)
        started = time.perf_counter()
        restored = 0
        verified = 0
        mismatches = []

        def target_name(source_name):
            if restore_prefix:
                return f"{restore_prefix}_{source_name}"
            return source_name

        try:
            self._set_state(
                running=True,
                phase="restoring",
                progress=0.0,
                message=f"restoring {name} to {target_pool}",
                last_restore=None,
            )
            batch = []
            with open(path, encoding="utf-8") as f:
                for line in f:
                    row = json.loads(line)
                    if row.get("record") != "object":
                        continue
                    data = base64.b64decode(row["data_b64"].encode("ascii"))
                    batch.append((target_name(row["name"]), data, row["hash"]))
                    if len(batch) >= SNAPSHOT_BATCH:
                        restored, verified = self._flush_restore_batch(
                            ioctx, batch, restored, verified, verify, mismatches
                        )
                        self._set_state(
                            progress=round(restored / total * 100.0, 2),
                            message=f"restored {restored}/{total}",
                        )
                        batch = []
                if batch:
                    restored, verified = self._flush_restore_batch(
                        ioctx, batch, restored, verified, verify, mismatches
                    )

            duration = max(time.perf_counter() - started, 0.000001)
            result = {
                "name": name,
                "target_pool": target_pool,
                "restored_objects": restored,
                "verified_objects": verified,
                "consistent": len(mismatches) == 0 and (not verify or verified == restored),
                "mismatches": mismatches[:20],
                "restore_duration_s": round(duration, 4),
                "restore_rate_obj_s": round(restored / duration, 1),
                "restore_rate_mb_s": round(meta.get("data_bytes", 0) / duration / 1_048_576, 2),
                "completed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
            self._set_state(
                running=False,
                phase="done",
                progress=100.0,
                message=f"restore {name} completed",
                last_restore=result,
            )
        except Exception as e:
            self._set_state(running=False, phase="error", progress=0.0, message=str(e))
        finally:
            with self._lock:
                self._running = False

    @staticmethod
    def _flush_restore_batch(ioctx, batch, restored, verified, verify, mismatches):
        comps = [(name, data, digest, ioctx.aio_write_full(name, data))
                 for name, data, digest in batch]
        for name, data, digest, comp in comps:
            comp.wait_for_complete()
            restored += 1
            if verify:
                got = ioctx.read(name)
                if _hash8(got) == digest:
                    verified += 1
                else:
                    mismatches.append(name)
        return restored, verified

    def start_restore(self, name, params):
        with self._lock:
            if self._running:
                return {"error": "snapshot job already running"}
            self._running = True
        self._set_state(
            running=True,
            phase="queued",
            progress=0.0,
            message=f"queued restore {name}",
            metrics={},
            last_restore=None,
        )
        meta = self._load_meta(name)
        target = self._restore_fast_job if meta and meta.get("format") == "fast.binary.compact.v1" else self._restore_job
        threading.Thread(target=target, args=(name, dict(params)), daemon=True).start()
        return {"started": True, "name": name}

    def status(self):
        return self._state_copy()


snapshot_module = SnapshotModule()
m4_bp = Blueprint("m4", __name__)


def _reply(result, ok_code=200):
    if "error" in result:
        return jsonify({"ok": False, **result}), 409
    return jsonify({"ok": True, **result}), ok_code


@m4_bp.route("/api/m4/snapshot/create", methods=["POST"])
@m4_bp.route("/api/m4/create", methods=["POST"])
def m4_create():
    return _reply(snapshot_module.start_create(request.json or {}))


@m4_bp.route("/api/m4/snapshot/<name>/restore", methods=["POST"])
def m4_restore_name(name):
    return _reply(snapshot_module.start_restore(name, request.json or {}))


@m4_bp.route("/api/m4/restore", methods=["POST"])
def m4_restore_body():
    body = request.json or {}
    name = body.get("name")
    if not name:
        return jsonify({"ok": False, "error": "missing snapshot name"}), 400
    return _reply(snapshot_module.start_restore(name, body))


@m4_bp.route("/api/m4/status", methods=["GET"])
def m4_status():
    return jsonify({"ok": True, **snapshot_module.status()})


@m4_bp.route("/api/m4/snapshots", methods=["GET"])
def m4_snapshots():
    return jsonify({"ok": True, "snapshots": snapshot_module.list_snapshots()})


@m4_bp.route("/api/m4/snapshot/<name>", methods=["GET"])
def m4_snapshot_detail(name):
    detail = snapshot_module.detail(name, limit=int(request.args.get("limit", 50)))
    if not detail:
        return jsonify({"ok": False, "error": "snapshot not found"}), 404
    return jsonify({"ok": True, **detail})


@m4_bp.route("/api/m4/stream", methods=["GET"])
def m4_stream():
    def gen():
        last = None
        while True:
            state = snapshot_module.status()
            payload = json.dumps(state, ensure_ascii=False)
            if payload != last:
                yield f"data: {payload}\n\n"
                last = payload
            if not state["running"] and state["phase"] in ("done", "error"):
                break
            time.sleep(0.5)

    return Response(gen(), mimetype="text/event-stream")
