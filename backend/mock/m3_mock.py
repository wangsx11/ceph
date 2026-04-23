# -*- coding: utf-8 -*-
"""M3 模块 Mock 数据生成器 — 跨节点对象读写与数据同步"""
import hashlib
import json
import random
import threading
import time
from datetime import datetime

from mock.config import (
    M3_CROSS_NODE_LATENCY_MAX, M3_CROSS_NODE_LATENCY_MIN,
    M3_WRITE_LATENCY_MS_MEAN, M3_WRITE_LATENCY_MS_STD,
)


def _ts():
    return datetime.now().strftime('%H:%M:%S')


def _compute_hash(data):
    if isinstance(data, str):
        data = data.encode('utf-8')
    return hashlib.md5(data).hexdigest()[:8]


def _get_obj_size(data):
    if isinstance(data, str):
        data = data.encode('utf-8')
    size = len(data)
    if size < 1024:
        return f"{size}B"
    return f"{size / 1024:.1f}KB"


def _mock_latency_ms():
    """生成 30-50μs 范围的延迟，转为 ms"""
    lat_us = random.gauss(
        (M3_CROSS_NODE_LATENCY_MIN + M3_CROSS_NODE_LATENCY_MAX) / 2,
        (M3_CROSS_NODE_LATENCY_MAX - M3_CROSS_NODE_LATENCY_MIN) / 6,
    )
    lat_us = max(M3_CROSS_NODE_LATENCY_MIN, min(M3_CROSS_NODE_LATENCY_MAX, lat_us))
    return round(lat_us / 1000, 3)  # μs -> ms


class MockSyncModule:
    """Mock 版本的 SyncModule，模拟跨节点同步行为"""

    def __init__(self):
        self._objects = {}  # name -> {data, version, created_by, modified_by, created_at, updated_at}
        self._lock = threading.Lock()

    def check_cluster(self):
        from config import SYNC_POOL, CURRENT_NODE, NODE_A, NODE_B
        with self._lock:
            total_bytes = sum(len(o["data"]) for o in self._objects.values())
            return {
                "cluster_fsid": "mock-fsid-0000-1111-2222-333344445555",
                "pool": SYNC_POOL,
                "pool_stats": {
                    "num_objects": len(self._objects),
                    "num_bytes": total_bytes,
                },
                "node_a": NODE_A,
                "node_b": NODE_B,
                "current_node": CURRENT_NODE,
            }

    def write_object(self, name, data_str, node):
        data_bytes = data_str.encode('utf-8') if isinstance(data_str, str) else data_str
        latency_ms = _mock_latency_ms()
        time.sleep(latency_ms / 1000)  # 模拟真实延迟
        now_str = _ts()
        h = _compute_hash(data_bytes)

        with self._lock:
            self._objects[name] = {
                "data": data_bytes,
                "version": 1,
                "created_by": node,
                "modified_by": node,
                "created_at": now_str,
                "updated_at": now_str,
            }

        return {
            "op": "WRITE",
            "name": name,
            "node": node,
            "size": _get_obj_size(data_bytes),
            "version": 1,
            "hash": h,
            "latency_ms": round(latency_ms, 1),
            "timestamp": now_str,
            "consistent": True,
        }

    def modify_object(self, name, data_str, node):
        data_bytes = data_str.encode('utf-8') if isinstance(data_str, str) else data_str
        latency_ms = _mock_latency_ms()
        time.sleep(latency_ms / 1000)
        now_str = _ts()
        h = _compute_hash(data_bytes)

        with self._lock:
            existing = self._objects.get(name)
            ver = (existing["version"] + 1) if existing else 1
            self._objects[name] = {
                "data": data_bytes,
                "version": ver,
                "created_by": existing["created_by"] if existing else node,
                "modified_by": node,
                "created_at": existing["created_at"] if existing else now_str,
                "updated_at": now_str,
            }

        return {
            "op": "MODIFY",
            "name": name,
            "node": node,
            "size": _get_obj_size(data_bytes),
            "version": ver,
            "hash": h,
            "latency_ms": round(latency_ms, 1),
            "timestamp": now_str,
            "consistent": True,
        }

    def delete_object(self, name, node):
        latency_ms = _mock_latency_ms()
        time.sleep(latency_ms / 1000)

        with self._lock:
            if name not in self._objects:
                return {"error": f"对象 {name} 不存在"}
            del self._objects[name]

        return {
            "op": "DELETE",
            "name": name,
            "node": node,
            "latency_ms": round(latency_ms, 1),
            "timestamp": _ts(),
            "consistent": True,
        }

    def list_objects(self):
        with self._lock:
            result = []
            for name, obj in self._objects.items():
                result.append({
                    "name": name,
                    "size": _get_obj_size(obj["data"]),
                    "version": obj["version"],
                    "hash": _compute_hash(obj["data"]),
                    "created_by": obj["created_by"],
                    "modified_by": obj["modified_by"],
                    "updated_at": obj["updated_at"],
                })
            return result

    def read_object(self, name):
        latency_ms = _mock_latency_ms()
        time.sleep(latency_ms / 1000)

        with self._lock:
            obj = self._objects.get(name)
            if obj is None:
                return {"error": f"对象 {name} 不存在"}
            return {
                "name": name,
                "data": obj["data"].decode('utf-8', errors='replace'),
                "size": _get_obj_size(obj["data"]),
                "version": obj["version"],
                "hash": _compute_hash(obj["data"]),
                "latency_ms": round(latency_ms, 1),
            }
