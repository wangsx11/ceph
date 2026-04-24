# -*- coding: utf-8 -*-
"""Simulation engine — used by performance metric 8.

Goals
-----
* Simulate N entities and M events in wall-clock time ≤ sim_duration_s.
* Persist entity state through RDMA mempool to exploit zero-copy.
* Aggregate events into PG-aligned batches for max throughput.
"""
import os
import random
import time

from ceph_manager import ceph
from config import SYNC_POOL
from rdma_mempool import MemPool


def run_simulation(entities: int, events: int, sim_duration_s: int) -> float:
    """Returns simulated-seconds that the engine was able to advance."""
    mp = MemPool("sim_engine", size_mb=min(1024, entities * 2 // 1024 + 64))
    handles = [mp.alloc(1024, hint="hot") for _ in range(entities)]
    payload = os.urandom(1024)
    for h in handles:
        mp.write(h, payload)

    # Drive the event loop.
    ioctx = ceph.ioctx(SYNC_POOL)
    sim_time = 0.0
    step = sim_duration_s / max(events // 1000, 1)
    wall_start = time.perf_counter()
    batch_size = 1024
    events_left = events
    while events_left > 0 and (time.perf_counter() - wall_start) < sim_duration_s * 2:
        b = min(batch_size, events_left)
        comps = []
        for k in range(b):
            idx = random.randint(0, entities - 1)
            mp.read(handles[idx])
            comps.append(ioctx.aio_write_full(f"sim_ev_{events_left - k:09d}", payload))
        for c in comps:
            c.wait_for_complete()
        events_left -= b
        sim_time += step

    # Cleanup.
    for h in handles:
        mp.free(h)
    return sim_time
